"""The Markdown reader: what counts as a command, a link, a code span, a history line."""

from docsdrift.docs import commands_of, parse_markdown, split_command, table_columns, table_header_for


def doc_of(text: str):
    return parse_markdown("README.md", text)


def test_fenced_block_lines_are_numbered_from_the_file():
    d = doc_of("# T\n\n```sh\nmytool --a\nmytool --b\n```\n")
    assert len(d.blocks) == 1
    assert d.blocks[0].lang == "sh"
    assert d.blocks[0].start == 4
    assert d.blocks[0].lines == ["mytool --a", "mytool --b"]
    cmds = commands_of(d)
    assert [(c.line, c.tokens) for c in cmds] == [(4, ["mytool", "--a"]), (5, ["mytool", "--b"])]


def test_tilde_fence_and_longer_fence_are_closed_correctly():
    d = doc_of("~~~bash\necho one\n~~~\n\n````\n```\ninner\n```\n````\nafter `span`\n")
    assert [b.lines for b in d.blocks] == [["echo one"], ["```", "inner", "```"]]
    assert [s.text for s in d.spans] == ["span"]


def test_code_spans_keep_their_line():
    d = doc_of("one\nuse `--flag` and ``--other``\n")
    assert [(s.line, s.text) for s in d.spans] == [(2, "--flag"), (2, "--other")]


def test_spans_inside_fences_are_not_spans():
    d = doc_of("```\n`not a span`\n```\n")
    assert d.spans == []


def test_links_reference_definitions_and_html():
    d = doc_of(
        "[a](docs/a.md) and [b](<docs/b c.md> \"title\")\n"
        "[ref]: docs/ref.md\n"
        "<img src=\"img/logo.png\" alt=\"x\">\n"
    )
    assert [(l.line, l.target, l.kind) for l in d.links] == [
        (1, "docs/a.md", "link"), (1, "docs/b c.md", "link"), (2, "docs/ref.md", "ref"), (3, "img/logo.png", "html"),
    ]


def test_link_written_inside_a_code_span_is_not_a_link():
    d = doc_of("write `[text](missing.md)` to make a link\n")
    assert d.links == []


def test_template_bindings_are_not_links():
    d = doc_of('<a :href="item.url">x</a>\n<a v-bind:href="u">y</a>\n<a class="b" href="real.md">z</a>\n')
    assert [l.target for l in d.links] == ["real.md"]


def test_html_comments_are_ignored():
    d = doc_of("<!-- [gone](missing.md) `npm run nothing` -->\n[kept](here.md)\n<!--\n[also](gone.md)\n-->\n")
    assert [l.target for l in d.links] == ["here.md"]
    assert d.spans == []


def test_front_matter_is_ignored():
    d = doc_of("---\ntitle: \"[x](missing.md)\"\n---\n\n[real](a.md)\n")
    assert [l.target for l in d.links] == ["a.md"]


def test_prompt_blocks_only_keep_prompt_lines():
    d = doc_of("```console\n$ mytool --run\noutput mentioning --not-a-flag\n$ mytool --again\n```\n")
    assert [c.tokens for c in commands_of(d)] == [["mytool", "--run"], ["mytool", "--again"]]


def test_line_continuations_are_joined():
    d = doc_of("```sh\nmytool \\\n  --first \\\n  --second\n```\n")
    cmds = commands_of(d)
    assert len(cmds) == 1
    assert cmds[0].line == 2
    assert cmds[0].tokens == ["mytool", "--first", "--second"]


def test_commands_are_split_at_shell_operators():
    d = doc_of("```sh\ncd app && mytool --x | tee log; other --y\n```\n")
    assert [c.tokens for c in commands_of(d)] == [["cd", "app"], ["mytool", "--x"], ["tee", "log"], ["other", "--y"]]


def test_command_substitution_lines_are_skipped():
    d = doc_of("```sh\nmytool --token $(cat secret)\n```\n")
    assert commands_of(d) == []


def test_non_shell_blocks_have_no_commands():
    d = doc_of("```python\nmytool --flag\n```\n```yaml\nrun: mytool --flag\n```\n")
    assert commands_of(d) == []


def test_inline_span_with_a_space_is_a_command():
    d = doc_of("Run `mytool --fast now` or just `mytool`.\n")
    cmds = commands_of(d)
    assert [(c.tokens, c.inline) for c in cmds] == [(["mytool", "--fast", "now"], True)]


def test_split_command_keeps_quotes_and_never_raises():
    assert split_command("a 'b c' \"d e\" f") == ["a", "'b c'", '"d e"', "f"]
    assert split_command("a 'unterminated b") == ["a", "'unterminated b"]
    assert split_command("") == []


def test_heading_path():
    d = doc_of("# A\n\n## B\n\ntext\n\n## C\n\nmore\n")
    assert d.heading_at(5) == "A > B"
    assert d.heading_at(9) == "A > C"


def test_stale_context_by_word_and_heading():
    d = doc_of("# Tool\n\n`--old` is deprecated\n\n`--new` works\n\n## Changelog\n\n`--gone` did things\n")
    assert d.stale_context(3) is True
    assert d.stale_context(5) is False
    assert d.stale_context(9) is True


def test_edit_mode_only_skips_explicit_history():
    d = doc_of(
        "# Tool\n\nfor example, if you pass `--name x`\n\n`--old` was removed\n\n## Troubleshooting\n\npass `--name`\n\n"
        "## Changelog\n\n`--name` added\n"
    )
    # an example sentence and a troubleshooting section are not history
    assert d.stale_context(3) is True and d.stale_context(3, edit=True) is False
    assert d.stale_context(9) is True and d.stale_context(9, edit=True) is False
    # an explicit history line and a changelog section are skipped in both modes
    assert d.stale_context(5, edit=True) is True
    assert d.stale_context(13, edit=True) is True


def test_table_cells_and_header():
    text = "| Option | Default |\n| --- | --- |\n| `--a|b` | `1` |\n"
    d = doc_of(text)
    assert table_columns(d.lines[2]) == ["`--a|b`", "`1`"]
    assert table_header_for(d, 3) == ["option", "default"]
    assert table_columns("no table here") == []


def test_unclosed_fence_does_not_raise():
    d = doc_of("```sh\nmytool --x\n")
    assert len(d.blocks) == 1
