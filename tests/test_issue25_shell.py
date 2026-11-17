"""#25: what the hook reads in a shell command: `cd` before the command, heredoc bodies, and code given to an interpreter. Nothing here runs a command: the hook
only reads the text. A is a repository under an enforced plan (its path has spaces), B a repository with no plan: the session of the table is opened in B, or in A."""
import unittest

from tests.test_v2_trust_fixes import HookBase

OWNED = 'src/a.txt'
NL = '\n'


class ShellBase(HookBase):
    def setUp(self):
        super().setUp()
        self.a = self.base / 'du an A'
        self.b = self.base / 'B'
        for repo in (self.a, self.b):
            (repo / '.git').mkdir(parents=True)
            for rel in ('other.txt', 'README.md', OWNED):
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text('x\n', encoding='utf-8')
        self.project_copy(self.a, owned=(OWNED,))
        self.af = str(self.a).replace('\\', '/')

    def ask(self, command, tool='Bash', inside=False):
        session = self.a if inside else self.b
        return self.check(tool, project=session, cwd=session, command=command)

    def blocked(self, command, tool='Bash', inside=False, reason=None):
        code, err = self.ask(command, tool, inside)
        self.assertEqual(code, 2, f'{command!r} should be blocked: {err}')
        if reason: self.assertIn(reason, err, command)
        return err

    def allowed(self, command, tool='Bash', inside=False):
        code, err = self.ask(command, tool, inside)
        self.assertEqual(code, 0, f'{command!r} should be allowed: {err}')

    def each(self, commands, method, **kw):
        for command in commands:
            with self.subTest(command=command): method(command, **kw)


class CdBeforeTheCommand(ShellBase):
    def test_cd_in_every_spelling_moves_the_paths_after_it(self):
        self.each([f'cd "{self.af}"; sed -i "s/o/x/" other.txt', f'cd "{self.af}" && echo hi > other.txt', f"cd '{self.af}' && echo hi > other.txt",
                   f'cd -- "{self.af}" && echo hi > other.txt', f'cd -P "{self.af}" && echo hi > other.txt', f'pushd "{self.af}" && echo hi > other.txt',
                   f'cd "{self.af}" || exit 1{NL}echo hi > other.txt', f'cd "{self.af}"{NL}rm other.txt'], self.blocked)

    def test_a_folder_without_spaces_needs_no_quotes(self):
        plain = self.base / 'plain'
        (plain / '.git').mkdir(parents=True)
        self.project_copy(plain, owned=(OWNED,))
        self.blocked(f'cd {str(plain).replace(chr(92), "/")} && echo hi > other.txt')

    def test_a_relative_cd_is_relative_to_the_directory_in_force(self):
        self.each(['cd "../du an A" && echo hi > other.txt', 'cd .. && cd "du an A" && echo hi > other.txt', 'cd "../du an A/src" && echo hi > ../other.txt'], self.blocked)
        self.allowed('cd "../du an A" && sed -i "s/a/x/" src/a.txt')
        self.allowed('cd "../du an A/src" && echo hi > a.txt')

    def test_reading_after_cd_is_not_a_write(self):
        self.allowed(f'cd "{self.af}" && cat other.txt && ls docs')
        self.allowed(f'cd "{self.af}" && grep -n x README.md | head')

    def test_a_cd_into_another_project_keeps_its_own_paths_there(self):
        b = str(self.b).replace('\\', '/')
        self.allowed(f'cd "{b}" && echo hi > other.txt')
        self.allowed(f'cd "{self.af}" && echo hi > "{b}/out.txt"')                  # absolute: B has no plan
        self.blocked(f'cd "{b}" && echo hi > "{self.af}/other.txt"')                # absolute into A

    def test_powershell_cd_forms(self):
        for command in (f'Set-Location -Path "{self.a}"; Set-Content other.txt x', f'Set-Location "{self.a}"; "x" | Out-File other.txt', f'sl "{self.a}"; Add-Content other.txt x',
                        f'cd "{self.a}"; Remove-Item other.txt', f'Push-Location -LiteralPath "{self.a}"; Set-Content other.txt x',
                        f'Set-Location -Path "{self.a}" && Set-Content other.txt x'):
            with self.subTest(command=command): self.blocked(command, 'PowerShell')
        self.allowed(f'Set-Location -Path "{self.a}"; Get-Content other.txt', 'PowerShell')
        self.allowed(f'Set-Location -Path "{self.a}"; Set-Content src/a.txt x', 'PowerShell')

    def test_a_cd_in_brackets_ends_at_the_bracket(self):
        self.blocked(f'(cd "{self.af}" && echo hi > other.txt)')
        self.allowed(f'(cd "{self.af}"); echo hi > other.txt')                      # the `cd` is over: this is B's other.txt
        self.allowed(f'(cd "{self.af}" && cat other.txt) && echo hi > other.txt')
        self.blocked(f'(cd "{self.af}"; echo a); cd "{self.af}"; echo hi > other.txt')

    def test_a_cd_in_a_pipeline_stage_does_not_carry_over(self):
        self.allowed(f'cd "{self.af}" | cat; echo hi > other.txt')
        self.allowed(f'echo x | cd "{self.af}"; echo hi > other.txt')
        self.allowed(f'cd "{self.af}" & echo hi > other.txt')

    def test_a_cd_that_cannot_be_read_makes_what_follows_unresolvable_where_a_plan_governs(self):
        self.blocked('cd "$X" && echo hi > other.txt', inside=True, reason='cannot resolve')
        self.blocked('cd "$X"; sed -i s/a/b/ other.txt', inside=True)
        self.allowed('cd "$X" && echo hi > other.txt')                              # session B: no plan governs any place
        self.allowed('cd "$X" && echo hi > /dev/null', inside=True)
        self.allowed(f'cd "$X" && echo hi > "{self.af}/src/a.txt"', inside=True)    # absolute and owned: nothing to guess

    def test_cd_into_the_project_makes_its_plan_judge_the_command_for_every_tool(self):
        self.blocked(f'cd "{self.af}" && git restore other.txt')
        self.blocked(f'cd "{self.af}/src" && git restore ../other.txt')
        self.allowed(f'cd "{self.af}" && git restore src/a.txt')

    def test_the_cd_inside_an_interpreter_string_is_followed_too(self):
        self.blocked(f"bash -c 'cd \"{self.af}\" && echo hi > other.txt'")
        self.blocked(f'powershell -c "Set-Location \'{self.a}\'; Set-Content other.txt x"')


class HeredocBodies(ShellBase):
    def hd(self, body, delim="<<'EOF'", end='EOF', head='python3 -', tail=''):
        return f'{head} {delim}{tail}{NL}{body}{NL}{end}'

    def test_a_body_that_only_compares_numbers_is_not_a_redirect(self):
        for body in ('x = 200' + NL + 'print(x>127)', 'x = 200' + NL + "if x > 127: print('big')", 'x = 3' + NL + 'print(x>=2)', 'print(9>5, 9>=55, 1>0)'):
            for delim in ("<<'EOF'", '<<EOF', '<<"EOF"'):
                with self.subTest(body=body, delim=delim):
                    self.allowed(self.hd(body, delim), inside=True)
                    self.allowed(f'cd "{self.af}"; ' + self.hd(body, delim))

    def test_the_dash_form_ends_at_an_indented_word(self):
        self.allowed(self.hd('\tprint(2>1)', '<<-EOF', '\tEOF'), inside=True)
        self.allowed(self.hd('\tx = 7' + NL + '\tprint(x>6)', '<<-EOF', '\tEOF'))

    def test_a_redirect_on_the_heredoc_line_is_a_real_write(self):
        self.blocked(self.hd('print(1)', tail=' > other.txt'), inside=True)
        self.blocked(f'cd "{self.af}"; python3 - <<\'EOF\' > other.txt{NL}print(1){NL}EOF')
        self.blocked(f'cat <<EOF > other.txt{NL}x{NL}EOF', inside=True)
        self.allowed(self.hd('print(1)', tail=' > src/a.txt'), inside=True)

    def test_a_body_fed_to_a_shell_is_still_shell_text(self):
        self.blocked(f'bash <<EOF{NL}echo hi > other.txt{NL}EOF', inside=True)
        self.blocked(f'sh -s <<\'EOF\'{NL}rm other.txt{NL}EOF', inside=True)
        self.allowed(f'bash <<EOF{NL}echo hi > src/a.txt{NL}EOF', inside=True)

    def test_a_body_that_is_text_is_not_judged_as_commands(self):
        self.allowed(f'cat > src/a.txt <<EOF{NL}rm other.txt{NL}echo x > other.txt{NL}EOF', inside=True)
        self.allowed(f'git commit -F - <<EOF{NL}fix: a > b and tee c{NL}EOF', inside=True)

    def test_a_real_write_target_that_is_only_digits_is_a_file(self):
        self.blocked('echo hi > 127', inside=True)
        self.blocked('echo hi >5', inside=True)
        self.blocked(f'cd "{self.af}" && echo hi > 127')
        self.allowed('echo hi 2>&1 | cat', inside=True)

    def test_two_heredocs_on_one_line_each_have_their_own_body(self):
        self.blocked(f"python3 - <<'A' 3<<'B'{NL}print(1){NL}A{NL}open('other.txt', 'w'){NL}B", inside=True)


class InterpreterCode(ShellBase):
    def hd(self, body, head='python3 -'):
        return f"{head} <<'EOF'{NL}{body}{NL}EOF"

    def test_python_writes_with_a_literal_path_are_judged_like_any_write(self):
        self.each([self.hd("open('other.txt', 'w').write('x')"), self.hd("open('other.txt','a').write('x')"), self.hd("open('other.txt', mode='x')"),
                   self.hd("open('other.txt', 'r+')"), self.hd("with open('other.txt', 'wb') as f: f.write(b'x')"),
                   self.hd("import json" + NL + "json.dump({}, open('other.txt', 'w'))"),
                   self.hd("from pathlib import Path" + NL + "Path('other.txt').write_text('x')"), self.hd("Path('other.txt').unlink()"),
                   self.hd("import shutil" + NL + "shutil.copy('README.md', 'other.txt')"), self.hd("shutil.rmtree('src')"), self.hd("shutil.move('README.md', 'other.txt')"),
                   self.hd("import os" + NL + "os.remove('other.txt')"), self.hd("os.rename('other.txt', 'src/b.txt')"), self.hd("os.makedirs('docs/new')")], self.blocked, inside=True)

    def test_reads_and_owned_writes_are_allowed(self):
        self.each([self.hd("print(open('other.txt').read())"), self.hd("open('other.txt', 'r').read()"), self.hd("open('other.txt', 'rb')"),
                   self.hd("open('src/a.txt', 'w').write('ok')"), self.hd("from pathlib import Path" + NL + "Path('src/a.txt').write_text('x')"),
                   self.hd("import os" + NL + "print(os.path.exists('other.txt'))"), self.hd("print(1)"), 'python3 script.py out.txt', 'python3 -c "print(3>2)"',
                   'python3 -c "print(open(\'other.txt\').read())"'], self.allowed, inside=True)

    def test_a_write_whose_path_or_mode_is_not_a_literal_is_refused_with_a_reason_about_the_code(self):
        for body in ("p = 'oth' + 'er.txt'" + NL + "open(p, 'w').write('x')", "open(sys.argv[1], 'w')", "open(f'{d}/x.txt', 'w')", "m = 'w'" + NL + "open('other.txt', m)",
                     "Path(d).joinpath('x').write_text('x')", "p.write_text('x')", "os.remove(name)", "Path('src') / 'a.txt'" + NL + "(Path('src') / 'a.txt').write_text('x')"):
            with self.subTest(body=body):
                err = self.blocked(self.hd(body), inside=True)
                self.assertIn('interpreter', err)
                self.assertNotIn('127', err)

    def test_inline_code_and_here_strings_are_read_too(self):
        self.each([f'cd "{self.af}" && python3 -c "open(\'other.txt\', \'w\').write(\'x\')"', f'cd "{self.af}" && node -e "require(\'fs\').writeFileSync(\'other.txt\', \'x\')"',
                   f'cd "{self.af}" && perl -e \'open(F, ">other.txt"); print F "x"\'', f'cd "{self.af}" && ruby -e "File.write(\'other.txt\', \'x\')"',
                   f'cd "{self.af}" && python3 - <<< "open(\'other.txt\', \'w\')"'], self.blocked)
        self.each(["python3 -c \"open('other.txt', 'w')\"", 'py -c "import os; os.remove(\'other.txt\')"'], self.blocked, inside=True)
        self.allowed('python3 -c "print(1)"', inside=True)

    def test_every_name_of_the_interpreter_counts(self):
        body = "open('other.txt', 'w')"
        self.each([self.hd(body, 'python'), self.hd(body, 'python3.12'), self.hd(body, 'py -3'), self.hd(body, '/usr/bin/python3 -'), self.hd(body, 'C:/Python313/python.exe -'),
                   self.hd(body, 'env PYTHONUTF8=1 python3 -'), self.hd(body, 'sudo python3 -')], self.blocked, inside=True)

    def test_node_perl_and_ruby_writes(self):
        self.each([self.hd("require('fs').writeFileSync('other.txt', 'x')", 'node -'), self.hd("fs.appendFile('other.txt', 'x', cb)", 'node'), self.hd("fs.rmSync('docs', {recursive: true})", 'node'),
                   self.hd("fs.renameSync('a.txt', 'other.txt')", 'node'), self.hd("fs.createWriteStream('other.txt')", 'node'), self.hd("fs.mkdirSync('docs/x')", 'node'),
                   self.hd("open(my $fh, '>', 'other.txt') or die;", 'perl'), self.hd("open(F, '>>other.txt');", 'perl'), self.hd("unlink 'other.txt';", 'perl'),
                   self.hd("rename 'a', 'other.txt';", 'perl'), self.hd("File.write('other.txt', 'x')", 'ruby'), self.hd("File.open('other.txt', 'w') { |f| f.puts 1 }", 'ruby'),
                   self.hd("FileUtils.rm_rf('docs')", 'ruby'), self.hd("File.delete('other.txt')", 'ruby')], self.blocked, inside=True)
        self.each([self.hd("console.log(fs.readFileSync('other.txt', 'utf8'))", 'node'), self.hd("open(F, '<other.txt');", 'perl'), self.hd("puts File.read('other.txt')", 'ruby'),
                   self.hd("File.open('other.txt') { |f| f.read }", 'ruby'), self.hd("fs.writeFileSync('src/a.txt', 'x')", 'node'), self.hd("open(F, '>src/a.txt');", 'perl')], self.allowed, inside=True)

    def test_the_computed_path_is_refused_only_where_a_plan_governs(self):
        body = "open(p, 'w')"
        self.allowed(self.hd(body))                                                 # session B, no cd: no plan governs the call
        self.blocked(self.hd(body), inside=True, reason='interpreter')
        self.blocked(f'cd "{self.af}"; ' + self.hd(body), reason='interpreter')     # a cd target is a place the command runs in, like the cwd

    def test_a_write_in_owned_code_through_cd_and_relative_paths(self):
        self.allowed(f'cd "{self.af}"; ' + self.hd("open('src/a.txt', 'w').write('ok')"))
        self.blocked(f'cd "{self.af}"; ' + self.hd("open('docs/hop-dong/x.json', 'w')"))
        self.blocked(f'cd "{self.af}/src"; ' + self.hd("open('../other.txt', 'w')"))

    def test_powershell_pipes_a_here_string_to_the_interpreter(self):
        self.blocked(f"@'{NL}open('other.txt', 'w'){NL}'@ | python -", 'PowerShell', inside=True)
        self.allowed(f"@'{NL}print(1){NL}'@ | python -", 'PowerShell', inside=True)


class WhereAGitCommandRuns(ShellBase):
    """Review P1-1: `git -C DIR`, `--work-tree`, `--git-dir` and `env -C DIR` run in DIR: that folder's plan judges the call, with HOOK30's git rules."""

    def test_git_c_into_a_from_b_is_judged_by_the_plan_of_a(self):
        self.each([f'git -C "{self.af}" checkout -- other.txt', f'git -C "{self.af}" restore other.txt', f'git -C "{self.af}" reset --hard', f'git -C "{self.af}" clean -fdx',
                   f'git -C "{self.af}" stash', f'git -C ../"du an A" checkout -- other.txt', f'git -C .. -C "du an A" checkout -- other.txt',
                   f'git --git-dir="{self.af}/.git" --work-tree="{self.af}" checkout -- other.txt', f'git --work-tree "{self.af}" checkout -- other.txt'], self.blocked)

    def test_reading_and_owned_work_through_git_c_stay_allowed(self):
        self.each([f'git -C "{self.af}" status', f'git -C "{self.af}" diff', f'git -C "{self.af}" log --oneline', f'git -C "{self.af}" checkout -- src/a.txt',
                   f'git --git-dir="{self.af}/.git" status'], self.allowed)

    def test_env_c_runs_the_command_in_that_folder(self):
        self.blocked(f'env -C "{self.af}" sh -c "echo hi > other.txt"')
        self.blocked(f'env -C "{self.af}" git checkout -- other.txt')
        self.allowed(f'env -C "{self.af}" git status')
        self.allowed('env -C "../B" sh -c "echo hi > other.txt"')

    def test_a_git_in_the_arguments_of_another_command_is_nothing(self):
        self.allowed(f'echo git -C "{self.af}" checkout other.txt')

    def test_git_c_into_a_from_a_is_still_judged_as_before(self):
        self.blocked(f'git -C "{self.af}" reset --hard', inside=True)
        self.allowed('git -C . status', inside=True)


class EscapedSpaces(ShellBase):
    """Review P1-2: in Bash `du\\ an\\ A` is one word (cd targets and write targets); PowerShell has no such escape."""

    def esc(self, path):
        return path.replace(' ', '\\ ')

    def test_cd_to_a_folder_whose_spaces_are_escaped(self):
        e = self.esc(self.af)
        self.each([f'cd {e} && echo hi > other.txt', f'cd {e} && git checkout -- other.txt', f'cd {e} && sed -i "s/x/y/" other.txt', f'cd {e}{NL}rm other.txt',
                   'cd ../du\\ an\\ A && echo hi > other.txt'], self.blocked)
        self.allowed(f'cd {e} && echo hi > src/a.txt')
        self.allowed(f'cd {e} && cat other.txt')

    def test_write_targets_with_escaped_spaces(self):
        e = self.esc(self.af)
        self.each([f'echo hi > {e}/other.txt', f'cp notes.txt {e}/other.txt', f'tee {e}/other.txt', f'touch {e}/other.txt', f'mv x {e}/other.txt', f'rm {e}/other.txt'], self.blocked)
        self.allowed(f'echo hi > {e}/src/a.txt')

    def test_a_backslash_that_is_a_path_separator_is_left_alone(self):
        self.blocked(f'echo hi > "{self.a}\\other.txt"')
        self.allowed(f'echo hi > {self.b}\\out.txt')


class ANestedStringWithEscapedQuotes(ShellBase):
    """Review P2-5: the string after `sh -c` / `bash -c` is read to its real end and unescaped."""

    def test_escaped_quotes_inside_the_string(self):
        self.each([f'sh -c "cd \\"{self.af}\\" && echo hi > other.txt"', f'bash -c "cd \\"{self.af}\\" && git checkout -- other.txt"',
                   f'sh -c "echo hi > \\"{self.af}/other.txt\\""'], self.blocked)
        self.allowed(f'sh -c "cd \\"{self.af}\\" && echo hi > src/a.txt"')
        self.allowed(f'sh -c "echo hi > \\"{str(self.b).replace(chr(92), "/")}/out.txt\\""')

    def test_single_and_plain_forms_still_work(self):
        self.blocked(f"bash -c 'cd \"{self.af}\" && echo hi > other.txt'")
        self.blocked(f'bash -c "cd \'{self.af}\' && echo hi > other.txt"')

    def test_inside_a_the_reason_names_the_file_not_a_cut_string(self):
        err = self.blocked('sh -c "echo hi > \\"other.txt\\""', inside=True)
        self.assertIn('other.txt', err)


class ScratchThroughTheExtendedPrefix(ShellBase):
    """Review P2-6: a `\\\\?\\` path is not trimmed by Windows, so `.onecrew.` is another folder, not scratch."""

    def write(self, path, inside=False):
        session = self.a if inside else self.b
        return self.check('Write', path, project=session, cwd=session)

    def test_the_extended_prefix_is_not_a_way_into_a_folder_that_only_looks_like_scratch(self):
        for inside in (False, True):
            code, err = self.write('\\\\?\\' + str(self.a) + '\\.onecrew.\\scratch\\x.txt', inside)
            self.assertEqual(code, 2, (inside, err))

    def test_scratch_itself_and_the_plain_windows_forms_stay_allowed(self):
        for inside in (False, True):
            for path in (str(self.a / '.onecrew' / 'scratch' / 'x.txt'), '\\\\?\\' + str(self.a / '.onecrew' / 'scratch' / 'x.txt')):
                with self.subTest(path=path, inside=inside):
                    code, err = self.write(path, inside)
                    self.assertEqual(code, 0, err)
        code, err = self.write(str(self.a) + '\\.onecrew\\scratch .\\x.txt', True)
        self.assertEqual(code, 0, err)

    def test_the_plain_form_of_a_prefixed_path_is_the_same_path(self):
        from pathlib import Path

        from onecrew.v2 import hook_cli
        self.assertEqual(hook_cli.plain_form('\\\\?\\D:\\x\\y'), Path('D:\\x\\y'))
        self.assertEqual(hook_cli.plain_form('\\\\.\\D:\\x'), Path('D:\\x'))
        self.assertEqual(hook_cli.plain_form(Path('D:\\x')), Path('D:\\x'))
