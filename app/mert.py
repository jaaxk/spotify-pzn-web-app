# app/mert.py
import os
import torch
import numpy as np
from transformers import AutoModel, AutoFeatureExtractor

MODEL_NAME = os.environ.get("MODEL_NAME", "m-a-p/MERT-v1-330M")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

class MERTEmbedder:
    def __init__(self, model_name=MODEL_NAME, device=DEVICE):
        self.device = device
        print(f"Loading model {model_name} on {self.device} — this can take a while.")
        self.model = AutoModel.from_pretrained(model_name, trust_remote_code=True).to(self.device)
        # Some models may have feature_extractor or processor; try to load one
        try:
            self.fe = AutoFeatureExtractor.from_pretrained(model_name, trust_remote_code=True)
        except Exception:
            self.fe = None

    def embed_audio(self, waveform, sr):
        """
        waveform: numpy array or torch tensor (1D) float32, in range [-1,1]
        sr: sample rate (should be 24000)
        Returns: 1D numpy vector of length 1024 (pooling across time)
        """
        # convert to torch
        if not isinstance(waveform, torch.Tensor):
            waveform = torch.tensor(waveform, dtype=torch.float32)
        waveform = waveform.to(self.device)

        # if the model expects batched input: add batch
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)

        # If feature extractor exists, use it to get model input
        inputs = {}
        if self.fe is not None:
            try:
                # feature_extractor expects numpy
                processed = self.fe(waveform.cpu().numpy(), sampling_rate=sr, return_tensors="pt")
                # move processed tensors to device
                inputs = {k: v.to(self.device) for k, v in processed.items()}
            except Exception:
                inputs = {"input_values": waveform}
        else:
            inputs = {"input_values": waveform}

        with torch.no_grad():
            out = self.model(**inputs, output_hidden_states=True, return_dict=True)

            # prefer last_hidden_state if available
            if hasattr(out, "last_hidden_state") and out.last_hidden_state is not None:
                features = out.last_hidden_state  # (batch, time, dim)
            elif hasattr(out, "hidden_states") and out.hidden_states:
                # average top layers if model returns hidden_states
                hidden = out.hidden_states[-1]
                features = hidden
            else:
                raise RuntimeError("Model did not return hidden states or last_hidden_state.")

            # mean pool across time dim (dim=1)
            pooled = features.mean(dim=1)  # (batch, dim)
            vec = pooled[0].cpu().numpy()
            # normalize vector to unit length (makes cosine work better)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec
