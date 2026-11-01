"""cuobjdump REG/STACK/CONSTANT/LOCAL gate between a baseline and a candidate engine build (pkg234).

    python scripts/dev/res_usage_compare.py BASE NEW [--stack-cap 64] [--reg-cap 254] [--filter SUBSTR]

BASE / NEW are an engine ``.pyd`` (``cuobjdump --dump-resource-usage`` is run on it) or a text file saved from
that command (``cuobjdump -res-usage X.pyd > base.txt``: save the baseline of the LIVE main build before editing).
Functions are matched by name with the per-build TU hash stripped. ``stageShadeBucketedKernel`` specialisations
are keyed by their template bools <HasPrincipled, HasTexture, HasPhotons, HasDispersion, HasLightPassAOVs,
HasProgram, HasNormalPerturb, HasAdd>.

Gate (exit 1 on failure):
  * every function that is not a HasTexture=true shade specialisation must be byte-identical (REG, STACK, LOCAL,
    every CONSTANT bank) to the baseline, except functions that exist only in NEW (reported, informational);
  * a HasTexture=true shade specialisation, and every stageShadowKernel (reaches the sampler via the textured-emitter
    NEE leg, see main()), must keep REG <= --reg-cap (default 254; or its baseline if higher) and STACK growth
    <= --stack-cap bytes (default 64) and must not gain LOCAL bytes.
ptxas spill stores are only in the nvcc ``-Xptxas -v`` build log; LOCAL growth is the proxy checked here.
"""
import argparse
import re
import subprocess
import sys


def parse(src):
    if src.lower().endswith(".txt"):
        text = open(src, encoding="utf-8", errors="replace").read()
    else:
        text = subprocess.run(["cuobjdump", "--dump-resource-usage", src], capture_output=True, text=True,
                              errors="replace", timeout=1800).stdout
    res, fn = {}, None
    for line in text.splitlines():
        m = re.match(r"\s*Function (\S+):", line)
        if m:
            fn = re.sub(r"\d*(_INTERNAL|_GLOBAL__N_)_[0-9a-f]{8}_\d+_([A-Za-z0-9_]+?)_cu_[0-9a-f]{8}(_\d+)?",
                        r"ANON_\2_", m.group(1))
            continue
        if fn and "REG:" in line:
            d = {k: int(v) for k, v in re.findall(r"(REG|STACK|LOCAL):(\d+)", line)}
            d["CONST"] = tuple(sorted((b, int(v)) for b, v in re.findall(r"CONSTANT\[(\d+)\]:(\d+)", line)))
            res[fn] = d
    return res


def shade_bools(name):
    m = re.search(r"stageShadeBucketedKernelI((?:Lb[01]E)+)E", name)
    return [c == "1" for c in re.findall(r"Lb([01])E", m.group(1))] if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("new")
    ap.add_argument("--stack-cap", type=int, default=64)
    ap.add_argument("--reg-cap", type=int, default=254)
    ap.add_argument("--filter", default="")
    a = ap.parse_args()
    base, new = parse(a.base), parse(a.new)
    bad, info = [], []
    for fn in sorted(set(base) | set(new)):
        if a.filter and a.filter not in fn:
            continue
        b, n = base.get(fn), new.get(fn)
        if b is None:
            info.append(f"NEW      {fn[:150]}  REG {n['REG']} STACK {n['STACK']}")
            continue
        if n is None:
            bad.append(f"MISSING  {fn[:150]}")
            continue
        bools = shade_bools(fn)
        textured = bool(bools and len(bools) > 1 and bools[1])
        # stageShadowKernel reaches the image-texture sampler through the textured-emitter NEE leg
        # (stage_advance.cu gpu_emissionTexelAtLightSample, gated by the RUNTIME flag c_wfEmissionTex, not a
        # template bool), so every instantiation links wf_sampleImageFiltered. pkg234 measured b26e8bb6: four
        # of five identical; <false,false,false,true> (HwOcc) REG 102 -> 117, same 2 blocks/SM at 256 threads,
        # and an interleaved GPU A/B vs main (cornell 1024^2 128spp OptiX, min-of-6): untextured -0.08 %,
        # Closest-textured +0.45 % (evidence/ab_shadow.log). So they take the textured-class budget.
        if "stageShadowKernel" in fn:
            textured = True
        if not textured:
            if b != n:
                bad.append(f"CHANGED  (must be identical) {fn[:150]}: {b} -> {n}")
        else:
            if n["REG"] > max(a.reg_cap, b["REG"]):
                bad.append(f"REG>{a.reg_cap}  {fn[:150]}: {b['REG']} -> {n['REG']}")
            if n["STACK"] - b["STACK"] > a.stack_cap:
                bad.append(f"STACK+{n['STACK'] - b['STACK']}  {fn[:150]}")
            if n["LOCAL"] > b["LOCAL"]:
                bad.append(f"LOCAL+{n['LOCAL'] - b['LOCAL']}  {fn[:150]}")
            if b != n:
                info.append(f"textured {''.join('1' if x else '0' for x in bools) if bools else fn[:60]}: REG {b['REG']} -> {n['REG']}"
                            f" STACK {b['STACK']} -> {n['STACK']} CONST {b['CONST']} -> {n['CONST']}")
    print(f"{len(base)} baseline vs {len(new)} candidate functions")
    for line in info:
        print("info:", line)
    for line in bad:
        print("FAIL:", line)
    print("GATE", "FAILED" if bad else "PASSED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
