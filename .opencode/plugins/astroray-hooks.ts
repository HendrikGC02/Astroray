import type { Plugin } from "@opencode-ai/plugin"
import { execSync } from "node:child_process"

// Port of .claude/hooks/*.ps1 to an opencode plugin.
// - pyd_shadow_guard      -> tool.execute.before (block .pyd edits; warn/block stale shadows)
// - pre_commit_diag_check -> tool.execute.before (block `git commit` carrying diag markers)
// - pre_push_signature_sweep -> tool.execute.before (warn-only stale-call-site sweep)
// - session_start         -> session.created (log git status + stale .pyd)
// All guards are fail-open: an unexpected error logs and never blocks.

const DIAG_MARKERS = /\[pkg\d+-diag\]|REMOVE AFTER|XXX DEBUG|printf[^\n]*pkg[^\n]*diag|\/\/ \[diag\]/
const PYD_WHITELIST = /^(build|build_cuda|build_tcnn|build_blender_addon[^/]*|dist)([\\/]|$)|^blender_addon[\\/]Release[\\/]/

function run(cmd: string, cwd: string): string {
  try {
    return execSync(cmd, { cwd, encoding: "utf8", maxBuffer: 128 * 1024 * 1024 }).toString()
  } catch {
    return ""
  }
}

function log(client: any, level: string, message: string) {
  client.app
    .log({ body: { service: "astroray-hooks", level, message } })
    .catch(() => {})
}

function findPydShadows(cwd: string): string[] {
  const tracked = run('git ls-files --cached "*.pyd"', cwd).split(/\r?\n/).filter(Boolean)
  const untracked = run('git ls-files --others --exclude-standard "*.pyd"', cwd).split(/\r?\n/).filter(Boolean)
  const all = Array.from(new Set([...tracked, ...untracked]))
  return all
    .map((p) => p.replace(/\\/g, "/"))
    .filter((p) => !PYD_WHITELIST.test(p))
}

function changedSymbols(cwd: string): string[] {
  const diff = run("git diff -U0 main...HEAD -- '*.py' '*.cpp' '*.hpp' '*.h' '*.cu' '*.cuh'", cwd)
  const symbols: string[] = []
  for (const line of diff.split(/\r?\n/)) {
    if (!line.startsWith("+")) continue
    let m
    if ((m = line.match(/^\+\s*(?:async\s+)?def\s+(\w+)/))) symbols.push(m[1])
    else if ((m = line.match(/^\+\s*class\s+(\w+)/))) symbols.push(m[1])
    else if ((m = line.match(/^\+\s*(?:inline\s+|static\s+|virtual\s+|const\s+)*[\w:<>,\s*&]+\s+(\w+)\s*\(/))) symbols.push(m[1])
  }
  return [...new Set(symbols)].filter((s) => s.length >= 4)
}

export const AstrorayHooks: Plugin = async ({ client, worktree, directory }) => {
  const root = worktree || directory || process.cwd()

  return {
    "tool.execute.before": async (input: any, output: any) => {
      const tool = input?.tool

      // 1. Block edits to .pyd binaries.
      if ((tool === "edit" || tool === "write" || tool === "apply_patch") && output?.args?.filePath) {
        if (String(output.args.filePath).toLowerCase().endsWith(".pyd")) {
          throw new Error("astroray-hooks: editing a .pyd binary is not allowed — rebuild from source instead.")
        }
      }

      if (tool !== "bash") return
      const cmd = String(output?.args?.command || "")

      // 2. Stale .pyd shadow guard on test/import invocations.
      if (/\bpytest\b|python\b[^\n]*\bastroray\b/.test(cmd)) {
        try {
          const shadows = findPydShadows(root)
          if (shadows.length) {
            const rootShadow = shadows.some((p) => !p.includes("/"))
            const msg = `Stale .pyd shadow(s) detected:\n  ${shadows.join("\n  ")}\nRebuild before running tests.`
            if (rootShadow) throw new Error(msg)
            log(client, "warn", msg)
          }
        } catch (e: any) {
          if (e instanceof Error && e.message.startsWith("Stale")) throw e
          log(client, "warn", `pyd shadow scan error: ${e}`)
        }
      }

      // 3. Block `git commit` carrying diagnostic markers.
      if (/\bgit\s+commit\b/.test(cmd)) {
        try {
          const staged = run("git diff --cached", root)
          const unstaged = run("git diff", root)
          const diff = staged + "\n" + unstaged
          if (DIAG_MARKERS.test(diff)) {
            const lines = diff.split(/\r?\n/).filter((l) => DIAG_MARKERS.test(l)).slice(0, 10).join("\n")
            throw new Error(`astroray-hooks: diagnostic markers found in the diff — remove before committing:\n${lines}`)
          }
        } catch (e: any) {
          if (e instanceof Error && e.message.startsWith("astroray-hooks: diagnostic")) throw e
          log(client, "warn", `diag-check error: ${e}`)
        }
      }

      // 4. Warn-only stale-call-site sweep on push / PR create.
      if (/\bgit\s+push\b|\bgh\s+pr\s+create\b/.test(cmd)) {
        try {
          const symbols = changedSymbols(root)
          if (symbols.length) {
            for (const s of symbols) {
              const hits = run(`git grep -l -w -- "${s}"`, root).split(/\r?\n/).filter(Boolean)
              const changed = run("git diff --name-only main...HEAD", root).split(/\r?\n/).filter(Boolean)
              const stale = hits.filter((f) => !changed.includes(f) && !/^(build|external|third_party)/.test(f))
              if (stale.length) log(client, "warn", `signature sweep: "${s}" has possible stale callers: ${stale.join(", ")}`)
            }
          }
        } catch (e) {
          log(client, "warn", `signature sweep error: ${e}`)
        }
      }
    },

    event: async ({ event }: any) => {
      if (event?.type !== "session.created") return
      try {
        const status = run("git status --short", root).trim() || "(clean)"
        const shadows = findPydShadows(root)
        const info = `Astroray session start. git: ${status.split(/\r?\n/).length - 1 || 0} changed file(s).`
        log(client, "info", info)
        if (shadows.length) log(client, "warn", `Stale .pyd shadow(s) present: ${shadows.join(", ")}`)
      } catch (e) {
        log(client, "warn", `session-start hook error: ${e}`)
      }
    },
  }
}
