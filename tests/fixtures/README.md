# Test fixtures

- `astronaut.jpg` - 256x256 crop of NASA's portrait of astronaut Eileen Collins, the same
  public-domain image scikit-image ships as `skimage.data.astronaut()`. NASA imagery is not
  subject to copyright (https://www.nasa.gov/nasa-brand-center/images-and-media/). Used only to
  test face detection and photo orientation.

Never add personal photos or crops of scanner output here: those live in the gitignored
`test-scans/` and are exercised only by `@pytest.mark.real_scans` tests.
