### Production Retrieval Results (All 66 Questions — Multiplier=3)
| Metric | Vector Only (FAISS) | BM25 Only | Hybrid (RRF k=60, default mult=3) | Raw Diff (Hybrid vs Vector) |
|:---|:---:|:---:|:---:|:---:|
| **Hit@1** | 84.9% (56/66) | 69.7% (46/66) | 84.9% (56/66) | +0 questions |
| **Hit@3** | 95.5% (63/66) | 89.4% (59/66) | 98.5% (65/66) | +2 questions |
| **Hit@5** | 98.5% (65/66) | 98.5% (65/66) | 100.0% (66/66) | +1 questions |
| **MRR**   | 0.9051 | 0.8091 | 0.9129 | +0.0078 |

### Tuning Set Results (46 Questions — Multiplier=3)
| Metric | Vector Only (FAISS) | BM25 Only | Hybrid (RRF k=60, default mult=3) | Raw Diff (Hybrid vs Vector) |
|:---|:---:|:---:|:---:|:---:|
| **Hit@1** | 82.6% (38/46) | 69.6% (32/46) | 82.6% (38/46) | +0 questions |
| **Hit@3** | 95.7% (44/46) | 91.3% (42/46) | 100.0% (46/46) | +2 questions |
| **Hit@5** | 100.0% (46/46) | 100.0% (46/46) | 100.0% (46/46) | +0 questions |
| **MRR**   | 0.8964 | 0.8130 | 0.9058 | +0.0094 |

### Held-out Test Set Results (20 Questions — Multiplier=3)
| Metric | Vector Only (FAISS) | BM25 Only | Hybrid (RRF k=60, default mult=3) | Raw Diff (Hybrid vs Vector) |
|:---|:---:|:---:|:---:|:---:|
| **Hit@1** | 90.0% (18/20) | 70.0% (14/20) | 90.0% (18/20) | +0 questions |
| **Hit@3** | 95.0% (19/20) | 85.0% (17/20) | 95.0% (19/20) | +0 questions |
| **Hit@5** | 95.0% (19/20) | 95.0% (19/20) | 100.0% (20/20) | +1 questions |
| **MRR**   | 0.9250 | 0.8000 | 0.9292 | +0.0042 |

### Multiplier Sensitivity (Multiplier=3 vs Multiplier=10)
> **Corpus Scale Note:** On this 24-chunk corpus, with $k=4$, a multiplier of 10 requests $\min(\max(4 \times 10, 60), 24) = 24$ candidates, which equals the entire corpus. In contrast, the production multiplier=3 fetches $\min(\max(12, 10), 24) = 12$ candidates (half the corpus).

| Evaluation Set | Multiplier | Hit@1 | Hit@3 | Hit@5 | MRR |
|:---|:---:|:---:|:---:|:---:|:---:|
| **Tuning Set (46 q)** | mult=3 (Default) | 82.6% | 100.0% | 100.0% | 0.9058 |
| **Tuning Set (46 q)** | mult=10 (Wider) | 82.6% | 100.0% | 100.0% | 0.9058 |
| **Held-out Set (20 q)** | mult=3 (Default) | 90.0% | 95.0% | 100.0% | 0.0000 |
| **Held-out Set (20 q)** | mult=10 (Wider) | 90.0% | 95.0% | 100.0% | 0.9292 |
| **All Questions (66 q)** | mult=3 (Default) | 84.9% | 98.5% | 100.0% | 0.0000 |
| **All Questions (66 q)** | mult=10 (Wider) | 84.9% | 98.5% | 100.0% | 0.9129 |
