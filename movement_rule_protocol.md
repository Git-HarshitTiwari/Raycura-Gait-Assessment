# Recorded movement checks

The assessment applies four checks to the exported angular waveform of a
single limb. Each waveform spans 101 points from 0% to 100% of the normalized
gait cycle. The checks and their source revision are defined in
[`raycura/myogait_rules.py`](raycura/myogait_rules.py). The adapted implementation
retains the [myogait license notice](raycura/MYOGAIT_LICENSE.txt).

| Recorded condition | Inclusive cycle window and threshold |
| --- | --- |
| Lower late knee flexion | Maximum knee angle over 60–100% < 40° |
| High late hip flexion with small ankle span | Maximum hip angle over 60–100% > 45° and whole-cycle ankle range < 15° |
| Elevated whole-cycle knee position | Minimum knee angle over 0–100% > 15° |
| Non-positive early ankle angle | Maximum ankle angle over 0–60% ≤ 0° |

The 60% sample belongs to both windows. The rules use exported zero. Historical
phase marks and reference curves are independent of these predicates.

A check reports a match, a non-match, or insufficient input to evaluate the
required motion. An evaluation records the limb, channel, window, observed
value, threshold, and source. The dashboard presents these findings for
review. Physical gait events, clinical diagnoses, and muscle causes require
independent evidence.
