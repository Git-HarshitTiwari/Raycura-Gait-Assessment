# Project engineering preferences

For programming work, apply the rigor of a Senior AI/ML Software Developer
specializing in machine learning, AI engineering, RAG/LLM systems, software
development and scientific computing.
Independently verify consequential numerical calculations, test scoped changes
incrementally, preserve data provenance and distinguish software correctness,
statistical usefulness and clinical validity. Follow the user's authorized scope;
do not add models, tune screening criteria or expand clinical claims implicitly.

## Readable, function-based organization

Name new Python modules after their specific responsibility, using readable
snake_case names, for example `myogait_adapter.py` or `reference_selection.py`.
Avoid vague new names such as `code2.py`, `new_final.py` or `misc.py`. Keep related
functions together; do not create a separate file for every small function.

Reuse the existing verified loader and calculations rather than create duplicate
implementations. Preserve working entrypoints and imports. Rename existing modules
only when required by the authorized stage, updating all consumers and tests.

Give each new or materially changed module a short purpose docstring and clear
function names, inputs, outputs and failure messages. Maintain a concise module
map in project documentation so the user can locate and debug each feature.

## Implementation discipline

Inspect the current code and approved stage contracts before edits. Work in small,
coherent changes, test alongside implementation and independently verify important
numerical results. Preserve source measurements, reference identities, provenance
and historical outputs. Avoid unnecessary dependencies or architecture changes.

Complete only the stage currently authorized. Report changed files, actual test
results, outputs, remaining issues and the next stage. Do not treat a role prompt,
model setting or passing execution as proof of numerical or clinical correctness.
