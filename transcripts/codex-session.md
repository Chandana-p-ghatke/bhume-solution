# Codex Session Transcript

User provided the BhuMe task contract and asked Codex to get started.

Codex read the contract and identified the required output: runnable code that reads a village bundle and writes `predictions.geojson` with `plot_number`, `status`, `confidence`, `method_note`, and geometry.

User provided the starter kit zip and public bundle links for Vadnerbhairav and Malatavadi.

Codex unpacked the starter kit, read `README.md`, `pyproject.toml`, `quickstart.py`, and the helper modules under `bhume/`. Codex downloaded both village bundles, installed the required Python geospatial dependencies into a local `.venv`, and ran the provided baseline scorer.

Baseline public-example scores observed:

```text
Vadnerbhairav: median IoU pred=0.713 vs official=0.612, improvement=+0.112
Malatavadi:   median IoU pred=0.588 vs official=0.510, improvement=+0.090
```

Codex then implemented `predict.py`, using this method:

1. Estimate a robust global shift from public example truths.
2. Convert plot geometries to a local metric CRS.
3. Read the rough `boundaries.tif` hint raster.
4. Blur the hint raster slightly so near-boundary alignment is rewarded.
5. For each plot, sample points around the polygon boundary.
6. Search local translations around the global drift.
7. Score each candidate by how well the shifted boundary samples land on boundary hints.
8. Assign confidence from boundary support, peak distinctness, agreement with the global shift, and plot size.
9. Flag weak or ambiguous cases instead of moving them.

Codex scored the new predictions locally:

```text
Vadnerbhairav: median IoU pred=0.815 vs official=0.612, improvement=+0.243
Malatavadi:   median IoU pred=0.778 vs official=0.510, improvement=+0.268
```

Codex added `METHOD.md`, copied user-facing outputs into `outputs/bhume-solution`, initialized a Git repository, added `.gitignore`, committed the solution, and helped push it to:

```text
https://github.com/Chandana-p-ghatke/bhume-solution
```

User then tested the uploaded predictions on the BhuMe self-score page. Codex noticed the first Vadnerbhairav upload used the wrong village file because the score showed IoU `0.000`; Codex instructed the user to upload the Vadnerbhairav-specific `predictions.geojson`. The corrected upload showed:

```text
Vadnerbhairav: 6 corrected, 0 flagged, median IoU 0.815, improvement +0.243
Malatavadi:   1 corrected, 2 flagged, median IoU 0.778, improvement +0.268
```

Final submission guidance from Codex:

- submit the GitHub repository URL
- include the predictions already committed in `data/.../predictions.geojson`
- include this `/transcripts` folder
- record a short video explaining the method, what worked, what broke, and what would be improved next
