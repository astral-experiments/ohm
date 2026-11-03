| Real workflow and phase | #337 (B) | C2 (B) | C3b (B) | #337 to C2 | #337 to C3b | C2 to C3b |
|---|---:|---:|---:|---:|---:|---:|
| Ruff #28106 cold | 1803.044 | 1884.222 | 1887.593 | -4.502% [-4.515, -4.486] | -4.691% [-4.703, -4.674] | -0.177% [-0.197, -0.168] |
| Ruff #28106 edit | 112.084 | 92.807 | 81.596 | +17.202% [+17.187, +17.234] | +27.194% [+27.180, +27.223] | +12.068% [+12.056, +12.092] |
| Ruff #28106 unchanged | 0.485 | 0.485 | 0.485 | -0.016% [-0.789, +0.018] | +0.009% [-0.009, +0.038] | +0.026% [-0.005, +0.786] |
| ty_server e2e #27836 cold | 2151.665 | 2274.022 | 2279.539 | -5.682% [-5.695, -5.671] | -5.942% [-5.956, -5.916] | -0.243% [-0.262, -0.226] |
| ty_server e2e #27836 edit | 31.209 | 32.306 | 32.356 | -3.519% [-3.538, -3.471] | -3.698% [-3.766, -3.583] | -0.164% [-0.238, -0.097] |
| ty_server e2e #27836 unchanged | 3.356 | 3.357 | 3.356 | +0.004% [-0.094, +0.020] | +0.012% [-0.003, +0.017] | +0.008% [-0.008, +0.091] |

Median absolute whole target plus shared allocated bytes, and largest individual descendant RSS (KiB), across the six actual boots.

| Workflow and phase | #337 bytes | C2 bytes | C3b bytes | #337 KiB | C2 KiB | C3b KiB |
|---|---:|---:|---:|---:|---:|---:|
| option old | 1,596,194,816 | 1,602,056,192 | 1,602,037,760 | 1,669,178 | 1,749,336 | 1,752,502 |
| option new | 1,600,757,760 | 1,606,619,136 | 1,606,596,608 | 842,808 | 933,566 | 916,960 |
| option unchanged | 1,600,757,760 | 1,606,621,184 | 1,606,596,608 | 63,678 | 63,628 | 63,516 |
| e2e old | 2,336,278,528 | 2,343,407,616 | 2,343,397,376 | 2,530,586 | 2,581,184 | 2,622,296 |
| e2e new | 2,343,749,632 | 2,350,895,104 | 2,350,868,480 | 730,752 | 758,008 | 753,434 |
| e2e unchanged | 2,343,751,680 | 2,350,903,296 | 2,350,868,480 | 65,450 | 65,546 | 65,400 |

Six separately booted, complete three-role blocks. Exact schedule counts for the primary edit:
Global upper tail: 8 720
P_C2 favorable boots 6 / 6; every >10% True ; every >2x False ; exact conditional upper tail [1, 8]
P_C3b favorable boots 6 / 6; every >10% True ; every >2x False ; exact conditional upper tail [1, 8]
C2_C3b favorable boots 6 / 6; every >10% True ; every >2x False ; exact conditional upper tail [1, 8]
Original, separate two-pair twofold screen: False
