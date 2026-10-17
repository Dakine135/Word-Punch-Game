"""Multiple-choice speech recognition with Whisper: "which on-screen word was that?"

Free transcription (Whisper/Parakeet) is poor on lone short words ("a", "I", "the" come out
as "Okay.", "Bye."...). Instead we let Whisper *score* each candidate the game is waiting
for and compare against its own free guess:

    score(c)  = average log-probability Whisper gives to transcript c for this audio
    free      = the same for Whisper's own greedy transcript
    accept the best candidate when score(best) >= free - margin   (otherwise: "not one of these")

That keeps Whisper's strong ears (good with kids' voices) while answering the question the
game actually asks, like Vosk's word list did.
"""
from __future__ import annotations

import os

import numpy as np


def _variants(word: str) -> list[str]:
    """How Whisper would write the word on its own."""
    w = word.strip()
    out = {f" {w}", f" {w}.", f" {w.capitalize()}.", f" {w.capitalize()}"}
    if len(w) == 1 and w.isalpha():  # a letter: Whisper writes "B." or "B"
        out |= {f" {w.upper()}.", f" {w.upper()}"}
    return sorted(out)


class WhisperChooser:
    def __init__(self, model_name: str = "openai/whisper-large-v3-turbo", device: str = "cuda"):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.torch = torch
        self.device = device if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.proc = WhisperProcessor.from_pretrained(model_name)
        self.model = WhisperForConditionalGeneration.from_pretrained(model_name, torch_dtype=self.dtype).to(self.device)
        self.model.eval()
        tok = self.proc.tokenizer
        tok.set_prefix_tokens(language="en", task="transcribe", predict_timestamps=False)
        self.prefix = tok.prefix_tokens  # <|startoftranscript|><|en|><|transcribe|><|notimestamps|>
        self.eos = tok.eos_token_id
        self.name = model_name.split("/")[-1]

    @staticmethod
    def _wrap(enc):
        from transformers.modeling_outputs import BaseModelOutput
        return BaseModelOutput(last_hidden_state=enc)

    def _encode(self, audio: np.ndarray):
        feats = self.proc(audio, sampling_rate=16000, return_tensors="pt").input_features
        feats = feats.to(self.device, self.dtype)
        with self.torch.no_grad():
            return self.model.model.encoder(feats).last_hidden_state

    def _score(self, enc, texts: list[str], batch: int = 24) -> list[float]:
        """Average log-prob per token (text + end) for each candidate transcript."""
        if len(texts) > batch:  # big word lists (letters: 26 x 6 spellings) would run out of GPU memory
            return [s for i in range(0, len(texts), batch) for s in self._score(enc, texts[i:i + batch], batch)]
        torch = self.torch
        tok = self.proc.tokenizer
        seqs = [self.prefix + tok.encode(t, add_special_tokens=False) + [self.eos] for t in texts]
        n = max(len(s) for s in seqs)
        ids = torch.full((len(seqs), n), self.eos, dtype=torch.long, device=self.device)
        for i, s in enumerate(seqs):
            ids[i, :len(s)] = torch.tensor(s, device=self.device)
        with torch.no_grad():
            out = self.model(encoder_outputs=self._wrap(enc.expand(len(seqs), -1, -1)), decoder_input_ids=ids[:, :-1])
            logp = torch.log_softmax(out.logits.float(), dim=-1)
        scores = []
        p = len(self.prefix)
        for i, s in enumerate(seqs):
            target = torch.tensor(s[p:], device=self.device)
            lp = logp[i, p - 1:len(s) - 1].gather(1, target[:, None]).squeeze(1)
            scores.append(float(lp.mean()))
        return scores

    def free(self, enc) -> tuple[str, float]:
        torch = self.torch
        with torch.no_grad():
            gen = self.model.generate(encoder_outputs=self._wrap(enc), decoder_input_ids=torch.tensor([self.prefix], device=self.device),
                                      max_new_tokens=12, do_sample=False)
        # (newer transformers return the prompt tokens too, older ones don't; specials are skipped either way)
        text = self.proc.tokenizer.decode(gen[0], skip_special_tokens=True).strip()
        return text, self._score(enc, [" " + text])[0] if text else -99.0

    def choose(self, audio: np.ndarray, candidates: list[str], floor: float = -2.0, with_free: bool = False):
        """Returns (best word or None, details). candidates: words the game is listening for.

        Accept the best-scoring candidate when its average log-prob >= floor. Calibrated on
        393 on-screen + 393 off-screen clips (adult and child-pitched): -2.0 caught 96/85/69%
        (adult / kid / high kid) with ~6% false alarms; -1.6 is stricter (5%), -2.5 looser (13%).
        """
        if not candidates:
            return None, {}
        enc = self._encode(audio)
        texts, owner = [], []
        for c in candidates:
            for v in _variants(c):
                texts.append(v)
                owner.append(c)
        scores = self._score(enc, texts)
        best = {}
        for c, s in zip(owner, scores):
            best[c] = max(best.get(c, -99.0), s)
        word, score = max(best.items(), key=lambda kv: kv[1])
        info = {"best": word, "score": score}
        if with_free:  # Whisper's own guess - only for display in the speech test tool
            info["free"], info["free_score"] = self.free(enc)
        return (word if score >= floor else None), info


def cuda_dlls() -> None:
    try:
        import torch
        lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if hasattr(os, "add_dll_directory") and os.path.isdir(lib):
            os.add_dll_directory(lib)
    except Exception:
        pass
