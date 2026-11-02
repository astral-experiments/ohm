# Cumulative rustc instructions after uv #21041

The corrected −22 control previously retired 17.245B instructions across the eight compilers that Cargo reran. With the external impl-directory change, they retired 9.018B. Halving the earlier control count would require a further 4.39% reduction. These figures came from separate studies. [Corrected control and callable stack](../../uv-21041-callable-check/cumulative-production) · [External impl directory](../../uv-21041-incoherent-impl-check/production)

The proposed comparison measures the corrected control and the generated-derive stack directly on a fresh host, using eight paired first edits spread over two independently built histories. All eight ratios must exceed 2×. This endpoint counts rustc instructions. The original study separately specifies ordinary Cargo wall time on uv #22958. [Cumulative instruction plan](cumulative-instructions.json) · [Original study including the wall-time endpoint](../preregistration)

I selected this comparison after the first stage1 pair and before building the release-optimized compiler. Both use the signed −22 Cargo. The control includes the #318 correctness repair.
