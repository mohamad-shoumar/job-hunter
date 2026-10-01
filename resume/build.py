#!/usr/bin/env python3
"""Build resume PDFs from text files.

  python3 build.py                     master (resume.md) -> output/Shoumar_Resume_General.pdf
  python3 build.py sync                copy the bullets and titles from the profile into resume.md
  python3 build.py new Backend Stripe [lead fullstack ...]
                                       copy the master to versions/Backend_Stripe_<MonYYYY>.md,
                                       print the optional bullets with those tags and the title
                                       for them, and add a row to applications.csv
  python3 build.py versions/X.md       that version -> output/Shoumar_X.pdf

Lines starting with // are notes: they are kept in the text file but never printed.

The bullets live in the profile (PROFILE), each tagged: [core] is always printed,
anything else only for jobs with that tag (see "Tailoring rules" there). `sync`
writes them into resume.md: core bullets as "- text", optional ones as
"// [tags] - text", and the role's title choices as "// titles: A [default] · B [lead]".
Edit bullets in the profile, then run sync; never edit them here.
"""
import csv
import html
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
MASTER = HERE / "resume.md"
VERSIONS = HERE / "versions"
OUTPUT = HERE / "output"
TRACKER = HERE / "applications.csv"
# This folder lives inside the job-hunter project, next to profile/.
PROFILE = HERE.parent / "profile" / "master_profile.md"
TRACKER_COLUMNS = ["Company", "Role", "Resume file", "Created", "Applied", "Status", "Notes"]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: Letter; margin: 0.5in 0.6in; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-variant-ligatures: none; font-family: Helvetica, Arial, sans-serif; font-size: 10pt; color: #222; line-height: 1.3; background: #fff; }
a { color: #5b9bd5; text-decoration: none; }
header { margin-bottom: 10pt; }
h1 { font-weight: normal; font-size: 25pt; color: #5b9bd5; line-height: 1.1; }
.title { font-size: 12pt; color: #5b9bd5; }
.contact { font-size: 10pt; margin-top: 4pt; }
h2 { font-weight: normal; font-size: 19pt; color: #5b9bd5; margin: 4pt 0 6pt; }
.job { margin-bottom: 8pt; }
p { margin-bottom: 8pt; }
.row { font-weight: bold; display: flex; justify-content: space-between; }
.date { flex-shrink: 0; font-weight: normal; white-space: nowrap; padding-left: 12pt; }
ul { list-style: disc outside; margin: 3pt 0 0 22pt; }
li { margin-bottom: 3pt; padding-left: 2pt; }
.skills { margin-bottom: 8pt; }
.skill { padding: 1.5pt 0; }
"""


# Add "compact: yes" to a file's header lines to squeeze it onto one page.
COMPACT_CSS = """
@page { margin: 0.4in 0.55in; }
body { font-size: 9.5pt; line-height: 1.25; }
header { margin-bottom: 6pt; }
h2 { font-size: 15pt; margin: 2pt 0 3pt; }
h1 { font-size: 22pt; }
li { margin-bottom: 1.5pt; }
.job, p, .skills { margin-bottom: 5pt; }
.skill { padding: 1pt 0; }
"""


def esc(text):
    # Escape HTML, then allow **bold** in the text file.
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text))


def build_html(lines, force_compact=False):
    info, name, body = {}, "", []
    in_job = in_list = in_table = False

    def close_list():
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    def close_block():
        nonlocal in_job, in_table
        close_list()
        if in_job:
            body.append("</div>")
            in_job = False
        if in_table:
            body.append("</div>")
            in_table = False

    seen_section = False
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("# "):
            name = line[2:].strip()
        elif not seen_section and not line.startswith("## ") and ":" in line:
            key, val = line.split(":", 1)
            info[key.strip().lower()] = val.strip()
        elif line.startswith("## "):
            seen_section = True
            close_block()
            body.append(f"<h2>{esc(line[3:].strip())}</h2>")
        elif line.startswith("### "):
            close_block()
            left, _, right = line[4:].partition("|")
            body.append('<div class="job">')
            body.append(f'<div class="row"><span>{esc(left.strip())}</span><span class="date">{esc(right.strip())}</span></div>')
            in_job = True
        elif line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{esc(line[2:].strip())}</li>")
        elif in_job:
            # Plain line under a ### heading = job title / subtitle.
            body.append(f'<div class="row">{esc(line)}</div>')
        elif ":" in line:
            # "Label: values" outside a job = skills row.
            if not in_table:
                body.append('<div class="skills">')
                in_table = True
            label, val = line.split(":", 1)
            body.append(f'<div class="skill"><b>{esc(label.strip())}:</b> {esc(val.strip())}</div>')
        else:
            close_list()
            body.append(f"<p>{esc(line)}</p>")
    close_block()

    contact = []
    if "email" in info:
        contact.append(f'<a href="mailto:{html.escape(info["email"])}">{html.escape(info["email"])}</a>')
    if "phone" in info:
        contact.append(html.escape(info["phone"]))
    # Profile links print as a short label; the URL lives in the link.
    for key, label in (("linkedin", "LinkedIn"), ("github", "GitHub")):
        if key in info:
            contact.append(f'<a href="{html.escape(info[key])}">{label}</a>')
    if "location" in info:
        contact.append(html.escape(info["location"]))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{html.escape(name)} Resume</title><style>{CSS}{COMPACT_CSS if force_compact or info.get("compact", "").lower() == "yes" else ""}</style></head>
<body>
<header>
  <div><h1>{html.escape(name)}</h1><div class="title">{html.escape(info.get("title", ""))}</div></div>
  <div class="contact">{" | ".join(contact)}</div>
</header>
{chr(10).join(body)}
</body></html>
"""


def build(src):
    OUTPUT.mkdir(exist_ok=True)
    name = "Resume_General" if src.resolve() == MASTER else src.stem
    out_pdf = OUTPUT / f"Shoumar_{name}.pdf"
    out_html = OUTPUT / f"Shoumar_{name}.html"
    lines = src.read_text().splitlines()
    # A CV that spills onto a second page is printed again in the compact layout.
    for compact in (False, True):
        out_html.write_text(build_html(lines, force_compact=compact))
        subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={out_pdf}", str(out_html)],
            check=True, stderr=subprocess.DEVNULL,
        )
        out_html.unlink()
        pages = len(re.findall(rb"/Type\s*/Page[^s]", out_pdf.read_bytes()))
        if pages <= 1:
            break
    print(f"Wrote {out_pdf.relative_to(HERE)} ({pages} page{'s' if pages != 1 else ''})"
          + (" in the compact layout" if compact else ""))
    if pages > 1:
        print("Warning: resume spills onto more than one page even when compact: cut a bullet.")


# --- the profile's bullets --------------------------------------------------------------

NOTE = re.compile(r"\s*\((?:Confirmed by me|mohamad answering)[^)]*\)\.?")
TAGGED = re.compile(r"\[([a-z, ]+)\]\s*(.*)$")
OPTIONAL = re.compile(r"^//\s*\[([a-z, ]+)\]\s*-\s+(.*)$")
TITLES = re.compile(r"^//\s*titles:\s*(.+)$", re.I)


def split_tags(text):
    """'[fullstack, lead] Built ...' -> ({'fullstack', 'lead'}, 'Built ...'). No tag means core."""
    m = TAGGED.match(text)
    if not m:
        return {"core"}, text
    return {t.strip() for t in m.group(1).split(",") if t.strip()}, m.group(2).strip()


def tag_text(tags):
    return ", ".join(sorted(tags))


def parse_titles(text):
    """'Algorithmic Trader [default] · Team Lead [lead]' -> [('Algorithmic Trader', {'default'}), ...]."""
    out = []
    for part in text.split("·"):
        m = re.match(r"^(.*?)\s*\[([a-z, ]+)\]$", part.strip())
        if m:
            out.append((m.group(1).strip(), {t.strip() for t in m.group(2).split(",")}))
        elif part.strip():
            out.append((part.strip(), {"default"}))
    return out


def pick_title(titles, tags):
    for title, want in titles:
        if want & set(tags) and "default" not in want:
            return title
    return next((title for title, want in titles if "default" in want), titles[0][0])


def dates_key(text):
    return " ".join(re.findall(r"[a-z0-9]+", re.sub(r"\bsept\b", "sep", text.lower())))


def profile_roles():
    """{dates key: (printed titles, [(tags, text), ...])} from the profile's Experience section."""
    text = PROFILE.read_text()
    body = re.split(r"^## ", text, flags=re.M)
    body = next((part for part in body if part.startswith("Experience")), "")
    roles, current = {}, None
    for raw in body.splitlines():
        line = NOTE.sub("", raw.strip()).strip()
        if line.startswith("### "):
            parts = re.split(r"\s{2,}", line[4:].strip())
            current = roles.setdefault(dates_key(parts[-1]), ([], []))
        elif current is None or not line or "TODO" in line:
            continue
        elif line.lower().startswith("printed title:"):
            current[0].extend(parse_titles(line.split(":", 1)[1]))
        elif line.startswith("- "):
            current[1].append(split_tags(line[2:].strip()))
    return roles


def sync():
    """Write the profile's bullets and title choices into resume.md's Experience roles."""
    if not PROFILE.is_file():
        sys.exit(f"No profile at {PROFILE}")
    roles = profile_roles()
    lines = MASTER.read_text().splitlines()
    out, section, i, done = [], "", 0, []
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("## "):
            section = s[3:].lower()
        if not (s.startswith("### ") and "experience" in section):
            out.append(line)
            i += 1
            continue
        role = roles.get(dates_key(s.partition("|")[2]))
        out.append(line)
        i += 1
        # The role's block runs to the next heading; its first plain line is the job title.
        block = []
        while i < len(lines) and not lines[i].strip().startswith("#"):
            block.append(lines[i])
            i += 1
        if role is None:
            out += block
            continue
        titles, bullets = role
        title = next((b.strip() for b in block if b.strip() and not b.strip().startswith(("//", "- "))), "")
        if titles:
            title = pick_title(titles, [])
        out.append(title)
        if titles:
            out.append("// titles: " + " · ".join(f"{t} [{tag_text(w)}]" for t, w in titles))
        out += [f"- {text}" for tags, text in bullets if "core" in tags]
        out += [f"// [{tag_text(tags)}] - {text}" for tags, text in bullets if "core" not in tags]
        out.append("")
        done.append(title)
    MASTER.write_text("\n".join(out).rstrip() + "\n")
    print(f"Synced {len(done)} roles from {PROFILE}: " + ", ".join(done))


def apply_tags(lines, tags):
    """Print the optional bullets whose tags match, and the title for those tags."""
    out = []
    for line in lines:
        s = line.strip()
        m = OPTIONAL.match(s)
        t = TITLES.match(s)
        if m and {x.strip() for x in m.group(1).split(",")} & set(tags):
            out.append(f"- {m.group(2).strip()}")
            continue
        if t:
            titles = parse_titles(t.group(1))
            # The title line is the last plain line above this one.
            for j in range(len(out) - 1, -1, -1):
                if out[j].strip() and not out[j].strip().startswith("//"):
                    out[j] = pick_title(titles, tags)
                    break
        out.append(line)
    return out


def known_tags(lines):
    tags = set()
    for line in lines:
        m = OPTIONAL.match(line.strip())
        t = TITLES.match(line.strip())
        if m:
            tags |= {x.strip() for x in m.group(1).split(",")}
        if t:
            for _, want in parse_titles(t.group(1)):
                tags |= want - {"default"}
    return tags


def new_version(role, company, tags=()):
    def clean(text):
        return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^A-Za-z0-9]+", text))

    today = date.today()
    VERSIONS.mkdir(exist_ok=True)
    dest = VERSIONS / f"{clean(role)}_{clean(company)}_{today.strftime('%b%Y')}.md"
    if dest.exists():
        sys.exit(f"{dest.relative_to(HERE)} already exists - edit that file instead.")
    lines = MASTER.read_text().splitlines()
    unknown = sorted(set(tags) - known_tags(lines))
    if unknown:
        sys.exit(f"Unknown tag(s): {', '.join(unknown)}. resume.md has: {', '.join(sorted(known_tags(lines)))}")
    lines = apply_tags(lines, tags)
    note = (f"// TAILORED for {company} - {role} ({today.strftime('%b %Y')}). "
            f"Tags: {', '.join(tags) if tags else 'none (core bullets only)'}.")
    if lines and lines[0].startswith("// MASTER RESUME"):
        lines[0] = note
    else:
        lines.insert(0, note)
    dest.write_text("\n".join(lines).rstrip() + "\n")

    is_new = not TRACKER.exists()
    with TRACKER.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(TRACKER_COLUMNS)
        writer.writerow([company, role, f"output/Shoumar_{dest.stem}.pdf", today.isoformat(), "", "Draft", ""])

    rel = dest.relative_to(HERE)
    print(f"Created {rel} (the master{' with ' + ', '.join(tags) if tags else ''}) and added it to applications.csv")
    print(f"Next: edit {rel}, then run: python3 build.py {rel}")


def main():
    args = sys.argv[1:]
    if not args:
        build(MASTER)
    elif args[0] == "sync":
        sync()
    elif args[0] == "new":
        if len(args) < 3:
            sys.exit('Usage: python3 build.py new <Role> <Company> [tag ...]   e.g. new Backend "Acme Corp" lead')
        new_version(args[1], args[2], args[3:])
    else:
        build(Path(args[0]))


if __name__ == "__main__":
    main()
