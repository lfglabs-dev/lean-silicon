# Streamed multiplier design-space results

| Radix | State bits | AND2/step | XOR2/step | Simple gates | GF cycles | Transaction cycles | Area×latency | Pareto |
|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1 | 273 | 128 | 131 | 259 | 128 | 161 | 41699 | yes |
| 2 | 273 | 256 | 262 | 518 | 64 | 97 | 50246 | yes |
| 4 | 273 | 512 | 524 | 1036 | 32 | 65 | 67340 | yes |
| 8 | 273 | 1024 | 1048 | 2072 | 16 | 49 | 101528 | yes |

* Radix 1 is exact minimum direct transition logic in this digit-serial family.
* Radix 8 reaches the 49-cycle protocol lower bound when output starts only after both operands arrive.
* All four points are Pareto-optimal under (state bits, direct digit-step gates, ideal cycles).
* State counts cover the MinCore arithmetic subcomponent, not the packetized top.
* These are architecture counts, not post-layout Sky130 area estimates.
