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


class TheProgramsOwnFolder(ShellBase):
    """Review 2 (P1-A, P1-B, P2-B): the targets taken from a program's arguments resolve against the folder that program runs in (`git -C`, `--work-tree`,
    `env -C`); a redirect is opened by the shell, so it resolves against the directory in force. GIT_WORK_TREE / GIT_DIR count as the flags."""

    def test_git_rm_and_mv_through_c_are_judged_like_in_a(self):
        self.each([f'git -C "{self.af}" rm other.txt', f'git -C "{self.af}" rm -f README.md', f'git -C "{self.af}" mv src/a.txt other2.txt',
                   f'git --work-tree="{self.af}" --git-dir="{self.af}/.git" rm other.txt'], self.blocked)
        self.blocked(f"git -C '{self.a}' rm other.txt", 'PowerShell')
        self.blocked('git rm other.txt', inside=True)

    def test_owned_and_cached_removals_stay_allowed(self):
        self.each([f'git -C "{self.af}" rm src/a.txt', f'git -C "{self.af}" rm --cached other.txt', f'git -C "{self.af}" status'], self.allowed)

    def test_a_redirect_after_env_c_is_the_shells_own(self):
        self.allowed(f'env -C "{self.af}" echo hi > notes2.txt')
        self.allowed(f'env -C "{self.af}" cat other.txt > copy.txt')
        self.blocked(f'env -C "{self.af}/src" echo hi > "../other.txt"', inside=True)
        self.blocked(f'env -C src/new echo hi > other.txt', inside=True)

    def test_a_redirect_after_git_c_is_the_shells_own_too(self):
        self.allowed(f'git -C "{self.af}" status > notes2.txt')
        self.blocked(f'git -C ../B status > "{self.af}/other.txt"')

    def test_the_programs_arguments_after_env_c_are_in_its_folder(self):
        self.blocked(f'env -C "{self.af}" touch other.txt')
        self.allowed(f'env -C "{self.af}" touch src/a.txt')

    def test_git_work_tree_and_git_dir_in_front_of_git(self):
        self.each([f'GIT_WORK_TREE="{self.af}" GIT_DIR="{self.af}/.git" git checkout -- other.txt', f'GIT_DIR="{self.af}/.git" GIT_WORK_TREE="{self.af}" git reset --hard',
                   f'GIT_WORK_TREE={self.af.replace(" ", chr(92) + " ")} git rm other.txt', f'export GIT_DIR="{self.af}/.git" GIT_WORK_TREE="{self.af}"; git checkout -- other.txt',
                   f'export GIT_WORK_TREE="{self.af}"\ngit rm other.txt'], self.blocked)

    def test_git_dir_alone_writes_in_the_session_folder(self):
        self.allowed(f'GIT_DIR="{self.af}/.git" git status')
        self.allowed(f'git --git-dir="{self.af}/.git" checkout -- other.txt')

    def test_powershell_env_assignments_count_too(self):
        self.blocked(f"$env:GIT_DIR='{self.a}\\.git'; $env:GIT_WORK_TREE='{self.a}'; git checkout -- other.txt", 'PowerShell')
        self.blocked(f"$env:GIT_WORK_TREE = '{self.a}'\ngit rm other.txt", 'PowerShell')

    def test_an_unreadable_work_tree_leaves_relative_arguments_unresolvable(self):
        self.blocked('GIT_WORK_TREE="$X" git rm other.txt', inside=True)
        self.blocked('git -C "$X" rm other.txt', inside=True)


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


class StreamDuplications(ShellBase):
    """#25 (review 3, P1-C): `2>&1` copies a descriptor; its `2` is no copy target."""
    COPIERS = ('cp ../B/README.md other.txt', 'mv ../B/README.md other.txt', 'Copy-Item ../B/README.md other.txt', 'Move-Item ../B/README.md other.txt')

    def test_a_copy_into_a_project_is_judged_with_a_duplication_at_the_end(self):
        for tail in ('2>&1', '1>&2', '>/dev/null 2>&1', '2>&1 >/dev/null'):
            for cmd in self.COPIERS:
                with self.subTest(cmd=cmd, tail=tail):
                    self.blocked(f'cd "{self.af}" && {cmd} {tail}')
                    self.blocked(f'{cmd} {tail}', inside=True)

    def test_an_owned_copy_with_a_duplication_is_allowed_in_the_project(self):
        for tail in ('2>&1', '1>&2', '>/dev/null 2>&1'):
            for cmd in ('cp ../B/README.md src/a.txt', 'Copy-Item ../B/README.md src/a.txt'):
                with self.subTest(cmd=cmd, tail=tail): self.allowed(f'{cmd} {tail}', inside=True)

    def test_a_duplication_before_the_arguments_and_closing_forms(self):
        self.blocked('cp 2>&1 ../B/README.md other.txt', inside=True)
        self.blocked('rm other.txt 2>&-', inside=True)
        self.allowed('cp ../B/README.md src/a.txt 0<&3', inside=True)

    def test_a_real_redirect_to_a_file_still_counts(self):
        self.blocked('cp ../B/README.md src/a.txt 2>&1 > other.txt', inside=True)
        self.blocked('echo hi >&other.txt', inside=True)


class AHeredocBodyStartsWhereTheCdLeftOff(ShellBase):
    """#25 (final review P1-1): a body a shell may run is judged in the folder in force at its `<<` line."""
    def body(self, git, head='bash', delim="<<'EOF'", cd=None):
        return f'cd "{cd or self.af}" && {head} {delim}{NL}{git}{NL}EOF'

    def test_a_git_form_that_throws_work_away_in_a_body_after_cd_is_refused_from_b(self):
        for git in ('git checkout -- other.txt', 'git restore other.txt', 'git checkout HEAD -- other.txt', 'git checkout -- *.txt', 'git checkout -- .',
                    'git checkout .', 'git restore docs/', 'git checkout other.txt', 'git stash push -- other.txt', 'git -C . checkout -- other.txt',
                    'set -e' + NL + 'git status' + NL + 'git checkout -- other.txt'):
            with self.subTest(git=git): self.blocked(self.body(git))

    def test_every_receiver_of_the_body_counts(self):
        for head, delim in (('sh', '<<EOF'), ('bash -s', "<<'EOF'"), ('bash', '<<"EOF"')):
            with self.subTest(head=head): self.blocked(self.body('git checkout -- other.txt', head, delim))
        self.blocked(f'cd "{self.af}" && cat <<\'EOF\' | bash{NL}git checkout -- other.txt{NL}EOF')
        self.blocked(f'cd "{self.af}"; bash <<\'EOF\'{NL}git restore other.txt{NL}EOF')
        self.blocked(self.body('git checkout -- other.txt', delim="<<'EOF' 2>&1"))

    def test_an_owned_path_in_the_body_is_allowed(self):
        self.allowed(self.body('git checkout -- src/a.txt'))
        self.allowed(self.body('git status; git diff'))

    def test_in_the_project_a_body_after_cd_to_a_subfolder_is_read_there(self):
        self.allowed(f'cd src && bash <<\'EOF\'{NL}git checkout -- a.txt{NL}EOF', inside=True)
        self.allowed(f'cd src && bash <<\'EOF\'{NL}git checkout -- *.txt{NL}EOF', inside=True)
        self.blocked(f'cd src && bash <<\'EOF\'{NL}git checkout -- ../other.txt{NL}EOF', inside=True)
        self.blocked(f'bash <<\'EOF\'{NL}git checkout -- other.txt{NL}EOF', inside=True)

    def test_a_cd_inside_the_body_still_counts(self):
        self.blocked(f'bash <<\'EOF\'{NL}cd "{self.af}" && git checkout -- other.txt{NL}EOF')

    def test_a_nested_string_after_cd_is_read_in_that_folder(self):
        self.blocked(f'cd "{self.af}" && bash -c "git checkout -- other.txt"')
        self.blocked(f"cd \"{self.af}\" && sh -c 'git restore other.txt'")


class AllStreamsRedirectsOfPowerShell(ShellBase):
    """#25 (final review P1-2): `*>`, `*>>`, `*>&1` are one operator; the `*` is no copy target."""
    def test_a_copy_into_a_project_with_all_streams_redirected_is_judged(self):
        for tail in ('*> $null', '*>$null', '*>&1', '*> log.txt', '-Force *>&1 | Out-String', '*>> log.txt'):
            for cmd in ('Copy-Item notes.txt', 'Move-Item notes.txt', 'cp notes.txt'):
                with self.subTest(cmd=cmd, tail=tail):
                    self.blocked(f'{cmd} "{self.a}\\other.txt" {tail}', 'PowerShell')

    def test_in_the_project_the_reason_names_the_file_and_an_owned_copy_passes(self):
        err = self.blocked('Copy-Item ..\\B\\notes.txt other.txt *> $null', 'PowerShell', inside=True)
        self.assertIn('other.txt', err)
        self.allowed('Copy-Item ..\\B\\README.md src\\a.txt *>&1', 'PowerShell', inside=True)
        self.allowed('Copy-Item ..\\B\\README.md src\\a.txt *> $null', 'PowerShell', inside=True)

    def test_the_redirect_target_of_all_streams_is_still_a_write(self):
        self.blocked('Get-Date *> other.txt', 'PowerShell', inside=True)
        self.allowed('Get-Date *> src\\a.txt', 'PowerShell', inside=True)


class AMoveChangesItsSourceToo(ShellBase):
    """FIX25B (Codex F1): `mv other.txt src/moved.txt` deletes other.txt: every source is judged, not only the destination."""
    def test_a_source_outside_owned_is_refused_in_every_spelling(self):
        self.each(['mv other.txt src/moved.txt', 'git mv other.txt src/moved-git.txt', 'mv -f other.txt README.md src/', 'mv -t src other.txt', 'mv --target-directory=src other.txt',
                   'move other.txt src\\moved.txt', 'cd "' + self.af + '" && mv other.txt src/moved.txt', 'sh -c "mv other.txt src/x.txt"'], self.blocked, inside=True)
        for command in ('Move-Item other.txt src\\moved.txt', 'Move-Item -Path other.txt -Destination src\\moved.txt', 'mi other.txt src\\moved.txt',
                        'Rename-Item other.txt moved.txt', 'ren other.txt moved.txt'):
            with self.subTest(command=command): self.blocked(command, 'PowerShell', inside=True)

    def test_a_move_entirely_inside_owned_and_a_copy_still_pass(self):
        self.project_copy(self.a, owned=('src/**',))
        self.each(['mv src/a.txt src/new/a2.txt', 'git mv src/a.txt src/new/a3.txt', 'mv -f src/a.txt src/new/', 'cp other.txt src/copied.txt'], self.allowed, inside=True)
        self.allowed('Move-Item src\\a.txt src\\new\\a4.txt', 'PowerShell', inside=True)

    def test_a_copy_is_not_a_change_to_its_source(self):
        self.project_copy(self.a, owned=('src/**',))
        self.allowed('cp -r other.txt README.md src/', inside=True)
        self.allowed('Copy-Item other.txt src\\c.txt', 'PowerShell', inside=True)


class AFolderChangeInsideASubstitutionOrAHeredoc(ShellBase):
    """FIX25B (Codex F2): where a git command runs when a `cd` sits in `$( )`, in a heredoc, or before a heredoc that is followed by a `popd`."""
    def test_a_cd_inside_a_command_substitution_moves_the_inner_command(self):
        self.each([f'x=$(cd "{self.af}" && git checkout -- other.txt)', f'echo $(cd "{self.af}" && git restore other.txt)', f'x=`cd "{self.af}" && git checkout -- other.txt`'],
                  self.blocked)

    def test_pushd_then_a_heredoc_body_runs_in_the_pushed_folder(self):
        self.blocked(f'pushd "{self.af}" && bash <<\'EOF\' && popd{NL}git checkout -- other.txt{NL}EOF')
        self.blocked(f'pushd "{self.af}"{NL}bash <<\'EOF\'{NL}git checkout -- other.txt{NL}EOF{NL}popd')

    def test_a_cd_inside_a_child_shell_body_does_not_move_the_parent(self):
        self.blocked(f'bash <<\'EOF\'{NL}cd src{NL}EOF{NL}git checkout -- other.txt', inside=True)
        self.allowed(f'bash <<\'EOF\'{NL}cd src{NL}git checkout -- a.txt{NL}EOF', inside=True)

    def test_the_line_after_a_body_that_changed_folder_runs_in_the_start_folder(self):
        # the child shell went to A, the parent stayed in B (no plan there): the line after EOF is B's
        self.allowed(f'bash <<\'EOF\'{NL}cd "{self.af}"{NL}EOF{NL}git checkout -- other.txt')

    def test_a_substitution_that_only_reads_stays_allowed(self):
        self.allowed(f'x=$(cd "{self.af}" && git status)')
        self.allowed('x=$(cd src && git checkout -- a.txt)', inside=True)


class AStarBeforeARedirectIsOnlyPowerShells(ShellBase):
    """FIX25B (Codex F3): in Bash `rm -f *>/dev/null` is the glob `*` and a redirect; only PowerShell reads `*>` as one operator."""
    def test_a_delete_with_a_glob_and_a_redirect_is_refused_in_bash(self):
        self.each(['rm -f *>/dev/null 2>&1', 'rm -f * >/dev/null 2>&1', 'rm *>/dev/null', 'rm -f *>>log.txt'], self.blocked, inside=True)

    def test_powershell_all_streams_redirects_still_pass(self):
        self.allowed('Copy-Item ..\\B\\README.md src\\a.txt *> $null', 'PowerShell', inside=True)
        self.allowed('Copy-Item ..\\B\\README.md src\\a.txt *>&1', 'PowerShell', inside=True)

    def test_a_bash_redirect_after_a_star_is_still_read(self):
        self.blocked('echo hi *>other.txt', inside=True)


class AChildCommandRunsWhereItStarts(ShellBase):
    """FIX25C (Codex R1 on 7b255e0): a `$( )`, backtick, `bash -c` string or heredoc body runs when its own segment runs, in the folder in force then: a `cd`
    LATER in the command does not move it (before the fix the hook judged it in the folder after that `cd`, let these through and refused the owned ones)."""
    def setUp(self):
        super().setUp()
        self.project_copy(self.a, owned=('src/**',))

    def from_src(self, command, tool='Bash'):
        return self.check(tool, project=self.a, cwd=self.a / 'src', command=command)

    def test_a_child_command_before_a_cd_runs_in_the_start_folder(self):
        self.each(['x=$(git checkout -- other.txt); cd src', 'echo "$(git checkout -- other.txt)" && cd src', f"bash <<'EOF' && cd src{NL}git checkout -- other.txt{NL}EOF",
                   'x=`git checkout -- other.txt`; cd src', "bash -c 'git checkout -- other.txt' && cd src", 'x=$(echo lost > other.txt); cd src',
                   f"bash <<'EOF' && cd src{NL}echo lost > other.txt{NL}EOF"], self.blocked, inside=True)
        self.blocked('$x = $(git checkout -- other.txt); Set-Location src', 'PowerShell', inside=True)

    def test_the_same_forms_on_the_owned_file_from_src_pass(self):
        for command, tool in (('x=$(git checkout -- a.txt); cd ..', 'Bash'), (f"bash <<'EOF' && cd ..{NL}git checkout -- a.txt{NL}EOF", 'Bash'),
                              ('x=`git checkout -- a.txt`; cd ..', 'Bash'), ('x=$(echo new > a.txt); cd ..', 'Bash'),
                              ('$x = $(git checkout -- a.txt); Set-Location ..', 'PowerShell')):
            with self.subTest(command=command):
                code, err = self.from_src(command, tool)
                self.assertEqual(code, 0, f'{command!r} should be allowed: {err}')

    def test_a_cd_before_the_child_still_moves_it(self):
        self.each(['cd src && x=$(git checkout -- a.txt)', f"cd src && bash <<'EOF'{NL}git checkout -- a.txt{NL}EOF",
                   f"pushd src && bash <<'EOF' && popd{NL}git checkout -- a.txt{NL}EOF"], self.allowed, inside=True)
        self.each([f"cd src && bash <<'EOF'{NL}cd ..{NL}git checkout -- other.txt{NL}EOF", 'cd src && x=$(cd .. && git checkout -- other.txt)'], self.blocked, inside=True)


class ARenameGivesANewNameInTheSourcesFolder(ShellBase):
    """FIX25C (Codex R2 on 7b255e0): `Rename-Item src/a.txt b.txt` makes src/b.txt, not b.txt where the shell is; a rename of a file outside owned or out of it is refused."""
    def setUp(self):
        super().setUp()
        self.project_copy(self.a, owned=('src/**',))

    def test_a_rename_inside_owned_passes_in_every_spelling(self):
        for command in ('Rename-Item src/a.txt b.txt', 'Rename-Item src\\a.txt b.txt', 'Rename-Item -Path src/a.txt -NewName b.txt',
                        'Rename-Item -LiteralPath "src/a.txt" -NewName:b.txt', 'Rename-Item -NewName b.txt -Path src/a.txt', 'ren src\\a.txt b.txt', 'rni src/a.txt b.txt -Force'):
            with self.subTest(command=command): self.allowed(command, 'PowerShell', inside=True)

    def test_a_rename_out_of_owned_or_of_a_file_outside_is_refused(self):
        for command in ('Rename-Item other.txt b.txt', 'Rename-Item -Path other.txt -NewName b.txt', 'Rename-Item src/a.txt ../x.txt', 'Rename-Item src/a.txt ..\\x.txt',
                        'ren other.txt src\\b.txt', 'Move-Item other.txt src/b.txt'):
            with self.subTest(command=command): self.blocked(command, 'PowerShell', inside=True)


class APowerShellSubexpressionMovesTheSession(ShellBase):
    """FIX25D (Codex C1 on 7781c08): in PowerShell the location belongs to the session, so a Set-Location inside `$( )` (or a pipeline stage, an `iex` string)
    moves every command after it; a bash `$( )` is a child shell and does not."""
    def setUp(self):
        super().setUp()
        self.project_copy(self.a, owned=('src/**',))

    def at(self, folder, command, tool='PowerShell'):
        return self.check(tool, project=self.a, cwd=folder, command=command)

    def test_a_location_change_inside_a_subexpression_moves_what_follows(self):
        for command in ('$x = $(Set-Location ..); git checkout -- other.txt', '$x = $(cd ..; Write-Output done); git checkout -- other.txt',
                        '$x = $(Set-Location ..); Set-Content other.txt LOST', '$x = $(Write-Output $(Set-Location ..)); git checkout -- other.txt',
                        '$x = "$(Set-Location ..) $(git checkout -- other.txt)"', 'Set-Location .. | Out-Null; Set-Content other.txt LOST',
                        "iex 'Set-Location ..'; git checkout -- other.txt", '& { Set-Location .. }; git checkout -- other.txt'):
            with self.subTest(command=command):
                code, err = self.at(self.a / 'src', command)
                self.assertEqual(code, 2, f'{command!r} should be blocked: {err}')

    def test_the_same_moves_into_owned_pass_and_a_quoted_subexpression_is_text(self):
        for folder, command in ((self.a, '$x = $(Set-Location src); git checkout -- a.txt'), (self.a, '$x = $(Set-Location src); Set-Content a.txt NEW'),
                                (self.a, '$x = $(cd src; git checkout -- a.txt)'), (self.a / 'src', "Write-Output '$(Set-Location ..)'; git checkout -- a.txt")):
            with self.subTest(command=command):
                code, err = self.at(folder, command)
                self.assertEqual(code, 0, f'{command!r} should be allowed: {err}')
        code, err = self.at(self.a, "Write-Output '$(Set-Location src)'; git checkout -- other.txt")
        self.assertEqual(code, 2, err)

    def test_bash_keeps_its_child_shell(self):
        code, err = self.at(self.a / 'src', 'x=$(cd ..); git checkout -- a.txt', 'Bash')
        self.assertEqual(code, 0, err)
        code, err = self.at(self.a, 'x=$(cd src); git checkout -- other.txt', 'Bash')
        self.assertEqual(code, 2, err)


class ABashPipelineStageIsAChildShell(ShellBase):
    """FIX25E (Codex P1 on 6acc82a): in bash a `cd` in a pipeline stage or sent to the background runs in a child shell: the commands after it run where the
    command was (`cd src | cat; git checkout -- other.txt` throws away other.txt at the top). `2>&1` and `&>` are redirects, not a background job."""
    def setUp(self):
        super().setUp()
        self.project_copy(self.a, owned=('src/**',))

    def test_a_cd_in_a_pipeline_or_the_background_does_not_move_what_follows(self):
        self.each(['cd src | cat; git checkout -- other.txt', 'cd src | cat; git restore other.txt', 'cd src | cat; echo LOST > other.txt',
                   'true | cd src; git checkout -- other.txt', 'cd src |& cat; git checkout -- other.txt', 'cd src & git checkout -- other.txt'], self.blocked, inside=True)

    def test_from_src_the_owned_file_passes_and_a_redirect_keeps_the_cd(self):
        code, err = self.check('Bash', project=self.a, cwd=self.a / 'src', command='cd .. | cat; git checkout -- a.txt')
        self.assertEqual(code, 0, err)
        for command in ('cd .. 2>&1; git checkout -- other.txt', 'cd .. &>/dev/null; git checkout -- other.txt'):
            with self.subTest(command=command):
                code, err = self.check('Bash', project=self.a, cwd=self.a / 'src', command=command)
                self.assertEqual(code, 2, err)
        self.each(['cd src 2>&1; git checkout -- a.txt', 'cd src && git checkout -- a.txt'], self.allowed, inside=True)

    def test_a_powershell_background_job_does_not_move_the_session(self):
        self.blocked('Set-Location src & git checkout -- other.txt', 'PowerShell', inside=True)
        self.allowed('& { Set-Location src }; git checkout -- a.txt', 'PowerShell', inside=True)


class ABackgroundListLeavesTheFolderUnsure(ShellBase):
    """FIX25F (Codex P1 on bd63367): `&` sends the whole list before it to the background (`cd src && true & git checkout -- other.txt` checks out at the top),
    so a `cd` in a command with a background job leaves the folder unsure: what follows is judged before and after the `cd`; a plain list keeps the `cd`."""
    def setUp(self):
        super().setUp()
        self.project_copy(self.a, owned=('src/**',))

    def test_a_cd_in_a_background_list_does_not_let_the_outside_file_through(self):
        self.each(['cd src && true & git checkout -- other.txt', 'cd src && true & git restore other.txt', 'cd src && true & echo LOST > other.txt',
                   'cd src || true & git checkout -- other.txt', 'pushd src && true & git checkout -- other.txt', '{ cd src; true; } & git checkout -- other.txt'],
                  self.blocked, inside=True)

    def test_a_list_without_a_background_job_keeps_its_cd(self):
        self.each(['cd src && true; git checkout -- a.txt', 'cd src 2>&1 && git checkout -- a.txt'], self.allowed, inside=True)
        self.allowed('Set-Location src; git checkout -- a.txt', 'PowerShell', inside=True)
