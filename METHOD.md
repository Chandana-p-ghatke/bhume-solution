# Method

`predict.py` implements a boundary-aware translation model for a whole village.

The method first estimates a robust village-wide centroid shift from the public
example truths. It then refines each plot independently by searching nearby
translations and scoring how well sampled points along the plot outline line up
with the rough `boundaries.tif` hint raster after a small blur. Confidence is
based on boundary support, how distinct the best shift is from nearby shifts,
agreement with the global drift, and plot size. Weak or ambiguous matches are
flagged and keep the official geometry.

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe predict.py data\34855_vadnerbhairav_chandavad_nashik
.\.venv\Scripts\python.exe predict.py data\12429_malatavadi_chandgad_kolhapur
```

Current public-example scores:

```text
Vadnerbhairav: median IoU 0.815 vs official 0.612, improvement +0.243, 6/6 corrected
Malatavadi:   median IoU 0.778 vs official 0.510, improvement +0.268, 1 corrected + 2 flagged
```
