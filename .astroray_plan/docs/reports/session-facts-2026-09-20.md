# Session facts — 2026-09-19 night → 2026-09-20 (lead: Claude Opus 5)

## Merged (7)
| PR | what | headline numbers |
|---|---|---|
| #836 | #827 MinGW GCC 15.2 compiles NanoVDB `grid_medium.cpp` (`-Wno-template-body`, GNU only) | CPU addon builds+stages again; 10 volume/#797 tests pass on that .pyd |
| #850 | viewport hotfix: material/light/geometry edits re-sync (stale replay since #831) | before: Base Color/move/light edits stale in both worker modes; after: all update. Cost ~125-132 ms/edit (#849) |
| #843 | Batch S — GPU renders native Principled emission (#835) + Cycles navigation samples | GPU/CPU 0.994-1.003 (main rendered 0.0); 128 shade kernels unchanged |
| #844 | Batch R — #825 texIdx key per (image, mapping), #826 two-input GPU op-VM programs; #822 → pkg277 | 349 vs 348 device functions, zero REG/STACK change; GPU/CPU 0.989-1.003 |
| #839 | Batch P — pkg276 IES×spot + GPU IES (A'), #840 lamp radius, #841 light Math fold, #834 Generated texspace | IES CPU+GPU vs Cycles-exact reference 1.000-1.003/bin; lighting_studio SPOT floor 0.02 → 1.04-1.10; REG 254 on 128/128, STACK +64 B on 4, perf neutral |
| #837 | Batch T — #767 observer fix (CIE 1964 10° → 1931 2°), #763 variance table, #779 addon parity leg | white-world tiles within 0.3 % of Cycles; #795 chrome green +8 % → +0.1 %; #767 ground G/B spread 5.4 → 0.6 pts; glass_sphere SSIM 0.774 → 0.855 |
| #838 | Batch Q — #828 GPU blackbody + device grid cache, pkg271 passes/volume_bounces/corpus/headless, #833 reported | GPU blackbody slab 0.989/0.984, fire 0.998/1.002; passes sum rel_L1 2.3e-5 CPU / 7e-6 GPU; absorption slab Tr 0.678/0.150/0.134 vs Cycles 0.687/0.153/0.135 (was 0.633 under 10°) |

## Specs
pkg276 done (#839), pkg271 done (#838), pkg277 filed (#822 coordinate-warp design).

## Issues
- Closed by merges: #835 #825 #826 #834 #840 #841 #767 #779 #828 #827 (+ the 15-line owner audit block run at session start: #741 #799 #392 #168 #143 #140 #137 #30 #29 #817 #818 #814 #807 #755 #795).
- Filed: #833 #834 #835 (lead), #840 #841 #842 #845 #846 #847 #848 #851 #852 #853 #854 #855 #856 #857 #858 #859 #860 #861.
- KNOWN_ISSUES: open addon-bug at P0/P1 3 → 1 (gate (e)).

## Method
- 5 Opus 5 lanes (P/Q/R/S/T) in sibling worktrees; lead ran every CUDA build (11 builds).
- Every lane diff got a deepseek-v4.1-flash critic pass; Opus reviewers (cpp-abi-guard, cycles-parity-reviewer) ran per PR through a Workflow; deepseek-v4-pro applied the agreed fixes.
- opencode spend: US$0.049 total (8 critic passes, 5 fix jobs, 1 implementation).
- Two usage-limit kills (02:55, 06:40); every lane resumed by raw agentId.
