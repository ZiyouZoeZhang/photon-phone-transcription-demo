# Next experiments

Baseline: base.en on CPU/int8; observed ~4-second delay. The receiver buffers up to 5 seconds, or ends after ~625ms low energy. Browser polling adds up to 650ms. Block boundaries can cut sentences. PCMU/8000 is narrowband: resampling does not restore lost frequencies.

Freeze/tag the working version before changing recognition. Benchmark the same short English script after each change; do not commit recordings.

1. LiveKit Inference streaming STT: try Deepgram Nova-3 or AssemblyAI Universal-Streaming on an opt-in branch. Published Build allowance includes $2.50 inference credit and a hard cap. Confirm actual remaining allowance before enabling. Credit-funded, not permanently free. Audio goes to cloud recognition providers. Measure actual accuracy/latency rather than assuming improvement.
2. Local MLX Whisper: Apple Silicon acceleration may make larger models practical. Compare base.en and small.en. Backend acceleration alone does not change accuracy. Memory use and latency require testing on the actual Mac.
3. Incremental decoding and real VAD: consider Whisper-Streaming or SimulStreaming. Emit partial hypotheses for display, final words for agent triggers. Merely shortening blocks to one second can worsen accuracy by losing context.

Measure speech-end-to-partial and speech-end-to-final separately, known-script error rate, inference time/audio duration, queue depth/drops, duplication, sentence clipping, product names/prices/negations. receivedAt currently measures event emission time, not end-to-end latency.

Official sources checked 2026-10-16:

- https://livekit.com/pricing/inference
- https://docs.livekit.io/deploy/admin/quotas-and-limits/
- https://docs.livekit.io/agents/models/stt/
- https://github.com/ml-explore/mlx-examples/tree/main/whisper
- https://github.com/ufal/whisper_streaming
- https://github.com/ufal/SimulStreaming
