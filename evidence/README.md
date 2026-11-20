# Evidence corpus

The JSON contains short authored paraphrases of four published sources and
one pinned software source. The papers carry DOI and primary-source links.
The software entry links the exact myogait revision for the numerical thresholds.
No raw patient rows are embedded. No external dataset enters model fitting.

The operational thresholds in config.json are engineering review thresholds.
The papers do not establish those thresholds for Raycura. The Attias study
imposed restrictions experimentally; its findings cannot be reversed into a
diagnosis from a curve. No medical reviewer has validated these rule cards yet.

RAG retrieves these versioned passages and the LLM selects permitted report
cards. The app renders approved text and exact calculated values, never arbitrary
medical prose from the model. The evidence hash and Ollama model digest are saved
with the retrieval index so stale embeddings are rejected.

The local retrieval index lives at `cache/rag/stage5_index.npz` on the project drive.
The local query includes the question and relevant card titles. When semantic
retrieval misses a source explicitly cited by a relevant card, the assistant
also supplies that card's registered source. Answers distinguish retrieved IDs
from linked IDs. On a retrieval or generation failure the same recording
supplies the fixed explanation. Run `python verify_local_assistant.py` to rebuild
and exercise the index and save the live results in `output/assistant_validation`.
