# `eeg_natus/` — Natus clinical EEG

The EDFs are **not in git** and cannot be: 103 channels at 512 Hz runs 85–172 MB per
recording, and GitHub hard-rejects anything over 100 MB. They are gitignored; keep
them here locally, or in Drive. This file is the provenance record.

## What arrived

Downloaded 31 July as `drive-download-20260731T073837Z-1-001.zip` (239 MB, CRC-clean).

| file | subject | start | duration |
|---|---|---|---|
| `Bui~ XuanBan_41df0ade….edf` | **ban** (participant 111240033) | 2026-07-29 14:40:48 | 1690.5 s |
| `Cao~ MinhAnh_d93a03a9….edf` | **minhanh** (participant 111240005) | 2026-07-29 16:29:20 | 1666.0 s |
| `Dao~ TrungThan_d76ac334….edf` | — no session, no Brain-Life recording | — | unreadable |

`Dao~ TrungThan` is **EDF+D (discontinuous)** and pyedflib refuses it outright
(`The file is discontinuous and cannot be read`). It also has no paired behavioural
session and no Brain-Life counterpart, so it is currently unusable on both counts.

## Montage

103 channels at 512 Hz: the 10–20 EEG set (C3 C4 Cz F3 F4 F7 F8 Fz Fp1 Fp2 Fpz A1 A2
O1 O2 Oz P3 P4 T5 T6 Pz T3 T4), five ECG leads, **E1/E2 EOG**, chin EMG, respiratory
and position channels, PPG, SpO2.

Three of those the Brain-Life band never had, and each removes a limitation the
earlier analysis had to work around:

* **O1 / O2 occipital** — where alpha actually lives. Brain-Life had only prefrontal
  bipolar derivations, where alpha is weakest.
* **E1 / E2 EOG** — a real ocular reference. Blink *correction* by regression becomes
  possible; with Brain-Life the only honest option was exclusion.
* **512 Hz, referential** — against 244 Hz bipolar.

## Only 8 of the 25 scalp channels carry real data

Checked by correlating every scalp channel against every other over a 120 s window
and collapsing anything above r = 0.99. The 25 scalp channels reduce to ~13 distinct
signals, and most of those are one signal appearing on many electrodes at 300–1300 µV
— far too large for EEG, and identical across electrodes, which is a floating or
shorted reference rather than brain activity:

| | shared-signal groups (NOT usable) | independent, plausible amplitude |
|---|---|---|
| ban | Fp2·F7·Fz·C3·P3·Oz·T5, F8·C4·Cz·Pz, Fp1·Fpz, P4·T6, **E1·E2** | F3 F4 T3 T4 O1 O2 A1 A2 (33–223 µV) |
| minhanh | Fp2·Fpz·F7·F8·Fz·C3·Oz·T5, C4·Cz·P4·Pz·T6, Fp1·P3, **E1·E2** | F3 F4 T3 T4 O1 O2 A1 A2 (44–184 µV) |

**The usable montage is the same eight electrodes in both recordings: F3, F4, T3, T4,
O1, O2, A1, A2.** Same set for both subjects, so this is a hardware or montage
problem, not something about either participant. It is still a workable reduced
montage — bilateral frontal, temporal and occipital, plus the A1/A2 ear references.

Two consequences:

* **E1/E2 are in a duplicate pair**, so the EOG is not independently usable and
  blink *correction* by regression is off the table after all. Exclusion remains the
  honest option, as with Brain-Life.
* Earlier numbers quoted for `Oz`, `Fp1` and `Fp2` (relative alpha ≈0.212, ratios
  1.03× / 0.92×) are meaningless — those channels are in the shared-signal groups.
  The O1/O2 alpha results below are unaffected, since O1 and O2 are both in the
  usable set.

## The timing now closes exactly

Natus EDFs carry an absolute start timestamp, which the Brain-Life CSVs never did:

| | session folder | Natus start | Natus end | `saved_at` |
|---|---|---|---|---|
| ban | 14:29:15 | 14:40:48 | 15:08:58 | 15:08:25 |
| minhanh | 16:29:18 | 16:29:20 | 16:57:06 | 16:56:57 |

Both Natus starts match their Brain-Life filename minute (14:40, 16:29), so the two
devices were started together and share a timebase. ban's 693 s gap between the
session folder and the recording is the demographics dialog plus the untimed SPACE
wait — exactly the unbounded interval flagged in `utils.INTRO_S`. minhanh's is 2 s,
i.e. that operator started recording immediately. This is the direct confirmation
that recordings begin at the SPACE press, which until now was only inferred.

## It overturns the verdict on minhanh

Eyes-closed alpha reactivity (relative alpha, eyes-open 20–80 s vs eyes-closed
130–190 s of the recording):

| | Brain-Life AF3 / AF4 | Natus O1 | Natus O2 | Natus F3 / F4 |
|---|---|---|---|---|
| ban | 1.36× / 1.29× | 1.43× | 2.09× | 1.95× / 1.93× |
| minhanh | **0.75× / 0.60×** | **1.89×** | **2.99×** | 1.73× / 1.68× |

minhanh has **normal, strong alpha reactivity** — stronger than ban's. The earlier
FAIL was a limitation of the Brain-Life prefrontal bipolar montage, not a
non-compliant participant. Anything in this repo that calls minhanh a negative
control on those grounds is wrong and should be read against this table.

What does *not* change: minhanh's Brain-Life recording still has its own problems
(the 13.25–14.5 Hz interference that failed the band-noise check, and a step
non-stationarity at ~383 s). Those are properties of that recording, not of the
participant, and the Natus data is unaffected by them.
