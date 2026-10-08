#!/usr/bin/env python3
"""Split skills/ into Claude Code plugins under plugins/ and write .claude-plugin/marketplace.json.

- gws-<service>[-helper] -> plugins/gws-<service>, persona-* -> gws-personas, recipe-* -> gws-recipes.
- A skill referenced (via ../<skill>/) by several plugins stays in skills/ and is copied into each.
- Skills listed in `requires.skills` that live in another plugin become plugin `dependencies`.

Rerunnable: run after `gws generate-skills`, or any time to rebuild from the current state.
Usage: python3 scripts/split-skills-to-plugins.py
"""
import json, os, re, shutil

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
version = json.load(open("package.json"))["version"]


def skill_dirs(base):
    return sorted(n for n in os.listdir(base) if os.path.isfile(f"{base}/{n}/SKILL.md")) if os.path.isdir(base) else []


# 1. Gather every skill back into skills/; a fresh copy in skills/ (from generate-skills) wins.
for p in sorted(os.listdir("plugins")) if os.path.isdir("plugins") else []:
    for n in skill_dirs(f"plugins/{p}/skills"):
        src = f"plugins/{p}/skills/{n}"
        if os.path.exists(f"skills/{n}"):
            shutil.rmtree(src)
        else:
            shutil.move(src, f"skills/{n}")

names = skill_dirs("skills")
gws = [n for n in names if n.startswith("gws-")]
text = {n: open(f"skills/{n}/SKILL.md").read() for n in names}
refs = {n: set(re.findall(r"\.\./([a-z0-9-]+)/", text[n])) & set(names) - {n} for n in names}


def home(n):
    if n.startswith("persona-"): return "gws-personas"
    if n.startswith("recipe-"): return "gws-recipes"
    # gws-gmail-reply-all -> gws-gmail (shortest existing prefix)
    return min((b for b in gws if n.startswith(b + "-")), key=len, default=n)


# 2. Each plugin holds its own skills plus everything they link to, transitively.
content = {}
for n in names:
    content.setdefault(home(n), set()).add(n)
for skills in content.values():
    todo = list(skills)
    while todo:
        for r in refs[todo.pop()] - skills:
            skills.add(r)
            todo.append(r)


def users(n):
    return [p for p, s in content.items() if n in s]


# Drop plugins made only of shared skills (e.g. gws-shared): they live in skills/ and in their users.
content = {p: s for p, s in content.items() if any(len(users(n)) == 1 for n in s)}
shared = {n for n in names if len(users(n)) > 1}
orphans = [n for n in names if not users(n)]
assert not orphans, f"skills in no plugin: {orphans}"

# 3. Move exclusive skills, copy shared ones.
for p, skills in content.items():
    os.makedirs(f"plugins/{p}/skills", exist_ok=True)
    for n in sorted(skills):
        if n in shared:
            shutil.copytree(f"skills/{n}", f"plugins/{p}/skills/{n}")
        else:
            shutil.move(f"skills/{n}", f"plugins/{p}/skills/{n}")


def required(n):
    m = re.search(r"^      skills:\n((?:        - .+\n)+)", text[n], re.M)
    return re.findall(r"- (\S+)", m.group(1)) if m else []


def desc(p):
    if p == "gws-personas": return "Google Workspace CLI persona skills (exec assistant, IT admin, sales ops, ...)."
    if p == "gws-recipes": return "Google Workspace CLI multi-step recipes combining several services."
    return re.search(r'^description:\s*"?(.*?)"?\s*$', text[p], re.M).group(1)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_json(path):
    return json.load(open(path)) if os.path.exists(path) else {}


# 4. Manifests. Existing extra fields (author, keywords, ...) are kept.
plugins = sorted(content)
for p in plugins:
    deps = sorted({users(r)[0] for n in content[p] for r in required(n)
                   if r not in content[p] and len(users(r)) == 1} - {p})
    path = f"plugins/{p}/.claude-plugin/plugin.json"
    manifest = load_json(path) | {"name": p, "version": version, "description": desc(p)}
    manifest.pop("dependencies", None)
    write_json(path, manifest | ({"dependencies": deps} if deps else {}))

market = load_json(".claude-plugin/marketplace.json")
write_json(".claude-plugin/marketplace.json", {"name": "googleworkspace-cli", "owner": {"name": "oh-my-capybara"}} | market | {
    "plugins": [{"name": p, "source": f"./plugins/{p}", "description": desc(p), "version": version} for p in plugins]})

# 5. Self-check: every ../ link resolves, inside skills/ and inside each plugin.
bad = [(d, r) for base in ["skills"] + [f"plugins/{p}/skills" for p in plugins]
       for n in skill_dirs(base) for d in [f"{base}/{n}"]
       for r in re.findall(r"\.\./[a-z0-9-]+/[A-Za-z0-9_./-]+\.md", open(f"{d}/SKILL.md").read())
       if not os.path.exists(os.path.join(d, r))]
assert not bad, f"broken links: {bad}"

stale = [p for p in os.listdir("plugins") if p not in content]
print(f"{len(names)} skills -> {len(plugins)} plugins; shared (kept in skills/, copied): {sorted(shared)}")
if stale:
    print(f"WARNING: plugins no longer generated, not in marketplace: {stale}")
