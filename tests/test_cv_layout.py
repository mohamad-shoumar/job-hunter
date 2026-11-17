"""resume/build.py's layout rules (it is a script in resume/, not part of the package)."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("cv_build", Path(__file__).parents[1] / "resume" / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
NB = " "


def test_the_last_four_words_wrap_together():
    assert build.keep_tail("cutting setup from a few hours to under 1 hour.") == \
        f"cutting setup from a few hours to{NB}under{NB}1{NB}hour."


def test_tags_are_never_touched_and_bold_text_counts_as_words():
    out = build.keep_tail('setup to <b>under 1 hour</b>. See <a href="https://x.y/a b">it</a>')
    assert '<a href="https://x.y/a b">' in out
    assert out == f'setup to <b>under 1{NB}hour</b>.{NB}See{NB}<a href="https://x.y/a b">it</a>'


def test_a_hyphen_or_slash_in_the_tail_cannot_break():
    out = build.keep_tail("microservices, TDD, Agile/Scrum, multi-agent orchestration, RAG")
    assert out == (f'microservices, TDD, <span class="nobr">Agile/Scrum,</span>'
                   f'{NB}<span class="nobr">multi-agent</span>{NB}orchestration,{NB}RAG')


def test_short_text_is_kept_whole():
    assert build.keep_tail("Python, SQL") == f"Python,{NB}SQL"


def test_every_bullet_skills_row_and_paragraph_gets_it():
    page = build.build_html([
        "# Jane Doe", "## Summary", "One two three four five six.", "## Skills", "Languages: Python, SQL, Go, Rust, C",
        "## Experience", "### Acme | 2020", "Engineer", "- Built a thing that does many useful things.",
    ])
    assert f"five{NB}six.</p>" in page
    assert f"Rust,{NB}C</div>" in page
    assert f"useful{NB}things.</li>" in page
