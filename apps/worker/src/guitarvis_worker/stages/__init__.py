"""One module per pipeline stage.

No stage imports another. The worker orchestrates them; they exchange plain
data defined in guitarvis_core.contracts.

Heavy dependencies (torch, demucs, basic_pitch, librosa) are imported inside
methods, never at module level, so that importing a stage does not require the
ml extra to be installed.
"""
