"""HOOK30 (#12): the hook refuses git forms that throw away uncommitted work outside the owned scope, and closes the holes found in the issue review:
temp variable with `..`, a read-only command that wraps a command substitution, `>|` `&>` `&>>` `>&file`, `sed -i` anywhere, Clear-Content,
New-Item -Force, and `rm` with recursive + force in any spelling. Nothing here runs a command: the hook only reads the text."""
import unittest

from tests.test_v2_trust_fixes import HookBase

OLD_DENY = ['rm -rf', r're:\b(git\s+)?(reset\s+--hard|clean\s+-[a-z]*f)']      # the deny list a plan exported by dev29 carries
OWNED = 'src/a.txt'


class GitGuardBase(HookBase):
    def setUp(self):
        super().setUp()
        for rel in ('other.txt', 'README.md', OWNED):
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text('x\n', encoding='utf-8')
        self.old = True

    def document(self, project, **kw):
        doc = super().document(project, owned=(OWNED,), **kw)
        doc['bash_deny'] = list(OLD_DENY) if self.old else []
        return doc

    def ask(self, command, tool='Bash', cwd=None):
        self.project_copy(self.repo)
        return self.check(tool, project=self.repo, cwd=cwd, command=command)

    def blocked(self, command, tool='Bash', way_out=False, cwd=None):
        code, err = self.ask(command, tool, cwd)
        self.assertEqual(code, 2, f'{command!r} should be blocked: {err}')
        if way_out: self.assertTrue('git worktree' in err and '.onecrew/scratch' in err, f'{command!r}: no safe way out in {err}')
        return err

    def allowed(self, command, tool='Bash', cwd=None):
        code, err = self.ask(command, tool, cwd)
        self.assertEqual(code, 0, f'{command!r} should be allowed: {err}')

    def each(self, commands, method, **kw):
        for command in commands:
            with self.subTest(command=command), self.subTest(old_export=self.old):
                method(command, **kw)


class GitPathForms(GitGuardBase):
    def test_checkout_with_paths_is_judged_per_path(self):
        self.each(['git checkout -- other.txt', 'git checkout HEAD -- other.txt', 'git checkout other.txt', 'git checkout .', 'git checkout -- .',
                   'git checkout HEAD~1 other.txt'], self.blocked)

    def test_checkout_of_an_owned_path_or_a_branch_stays_allowed(self):
        self.each(['git checkout -- src/a.txt', 'git checkout feature', 'git checkout -b topic', 'git checkout -b topic feature', 'git checkout -'], self.allowed)

    def test_restore_is_judged_per_path_except_when_it_only_unstages(self):
        self.each(['git restore other.txt', 'git restore --source=HEAD~1 other.txt', 'git restore -s HEAD~1 other.txt', 'git restore .', 'git restore -SW other.txt',
                   'git restore --worktree other.txt', 'git restore -p'], self.blocked)
        self.each(['git restore src/a.txt', 'git restore --staged other.txt', 'git restore -S other.txt'], self.allowed)

    def test_stash_with_paths_is_judged_per_path(self):
        self.blocked('git stash push other.txt')
        self.blocked('git stash push -m wip other.txt src/a.txt')
        self.allowed('git stash push src/a.txt')
        self.allowed('git stash push -m wip src/a.txt')

    def test_git_dash_c_exe_and_the_cd_before_it_are_followed(self):
        self.each(['git -C . checkout -- other.txt', 'git.exe checkout -- other.txt', 'cd src && git restore ../other.txt', 'git status; git restore other.txt',
                   'git diff | cat; git checkout -- other.txt', 'sudo git restore other.txt', '(git restore other.txt)'], self.blocked)
        self.allowed('cd src && git restore a.txt')
        self.allowed('git -C src restore a.txt')

    def test_a_path_that_cannot_be_read_is_refused(self):
        self.each(['git checkout -- $F', 'git restore "$F"', 'git checkout $F'], self.blocked)

    def test_powershell_gets_the_same_verdicts(self):
        for command in ('git checkout -- other.txt', 'git restore other.txt', 'git stash', 'git reset --hard'):
            with self.subTest(command=command): self.blocked(command, 'PowerShell')
        for command in ('git status', 'git restore src/a.txt'):
            with self.subTest(command=command): self.allowed(command, 'PowerShell')

    def test_commands_inside_substitutions_and_interpreter_strings_are_read(self):
        self.each(['echo $(git stash)', 'echo `git restore other.txt`', "bash -c 'git checkout -f'", 'powershell -c "git stash drop"'], self.blocked)


class GitAlwaysRefused(GitGuardBase):
    def test_forced_checkout_and_switch_name_a_safe_way(self):
        self.each(['git checkout -f', 'git checkout -f main', 'git checkout --force main', 'git checkout -fb x', 'git switch -f main', 'git switch --force main',
                   'git switch --discard-changes main', 'git checkout -p'], self.blocked, way_out=True)

    def test_every_stash_form_but_list_show_and_owned_paths_is_refused(self):
        self.each(['git stash', 'git stash -u', 'git stash push', 'git stash save wip', 'git stash drop', 'git stash clear', 'git stash pop', 'git stash apply',
                   'git stash branch x', 'git status && git stash'], self.blocked, way_out=True)
        self.each(['git stash list', 'git stash show', 'git stash show -p'], self.allowed)

    def test_reset_hard_merge_keep_anywhere_on_the_line(self):
        self.each(['git reset --hard', 'git reset -q --hard', 'git reset --hard HEAD~1', 'git reset HEAD~1 --hard', 'git reset --merge', 'git reset --keep HEAD~1'],
                  self.blocked, way_out=True)
        self.each(['git reset', 'git reset --soft HEAD~1', 'git reset --mixed', 'git reset src/a.txt', 'git reset -q HEAD -- other.txt'], self.allowed)

    def test_clean_with_force_anywhere_unless_dry_run(self):
        self.each(['git clean -f', 'git clean -fd', 'git clean -d -f', 'git clean --force', 'git clean -x -d -f', 'git clean -e keep -f'], self.blocked, way_out=True)
        self.each(['git clean -n', 'git clean -n -d', 'git clean --dry-run -d'], self.allowed)
        self.old = False                                       # `-fn` is a dry run; only the old deny list (clean -f... as text) still blocks it
        self.allowed('git clean -fn')

    def test_checkout_index_force_and_read_tree_update(self):
        self.each(['git checkout-index -f -a', 'git checkout-index --force -a', 'git read-tree -u --reset HEAD', 'git read-tree -mu HEAD'], self.blocked, way_out=True)
        self.each(['git checkout-index -a', 'git read-tree HEAD'], self.allowed)

    def test_everyday_git_stays_allowed(self):
        self.each(['git status', 'git status --short', 'git diff', 'git log --oneline -3', 'git add src/a.txt', 'git commit -m "fix a"', 'git switch feature',
                   'git switch -c topic2', 'git worktree add ../wt-x feature', 'git branch -d topic', 'git commit -m "docs: stash and checkout -f notes"'], self.allowed)

    def test_an_active_plan_exported_by_a_newer_version_gets_the_same_verdicts(self):
        self.old = False
        self.blocked('git reset --hard', way_out=True)
        self.blocked('git checkout -- other.txt')
        self.allowed('git checkout -- src/a.txt')


class TempVariableEscape(GitGuardBase):
    def test_dotdot_after_a_temp_variable_is_an_ordinary_target(self):
        self.each(['echo x > $TMPDIR/../other.txt', 'cp README.md $TEMP/../x.txt', 'echo x > $TMPDIR/a/../../other.txt', 'rm -r -f $TMPDIR/..'], self.blocked)
        self.blocked('Remove-Item $env:TEMP\\.. -Recurse -Force', 'PowerShell')
        self.blocked('Set-Content %TEMP%\\..\\x.txt y', 'PowerShell')

    def test_a_file_inside_the_temp_variable_stays_allowed(self):
        self.each(['echo x > $TMPDIR/f.txt', 'echo x > $TEMP/sub/f.txt', 'cp README.md $TMPDIR/copy.txt'], self.allowed)


class ReadOnlyWrapper(GitGuardBase):
    def test_a_substitution_in_a_read_only_segment_is_judged(self):
        sub = f"python -c \"import shutil; shutil.copy('README.md', '{self.state.as_posix()}/plans/x.md')\""
        self.each([f'cat $({sub})', f'cat `{sub}`', f'cat <({sub})', f'ls >({sub})'], self.blocked)

    def test_a_plain_read_only_command_stays_read_only(self):
        self.each([f'cat {self.state.as_posix()}/plans/owner-rules.md', 'cat README.md', 'ls -la'], self.allowed)

    def test_a_write_inside_a_read_only_substitution_is_a_write(self):
        self.blocked('cat $(cp README.md other.txt)')


class RedirectsAndInPlaceEdits(GitGuardBase):
    def test_every_write_redirect_form_is_a_write(self):
        self.each(['echo x >| other.txt', 'echo x &> other.txt', 'echo x &>> other.txt', 'echo x >& other.txt', 'echo x > other.txt'], self.blocked)

    def test_descriptor_copies_and_owned_targets_stay_allowed(self):
        self.each(['echo x >&2', 'echo x >&1', 'echo x 2>&1', 'echo x > /dev/null', 'echo x > src/a.txt', 'echo x >| src/a.txt', 'echo x &> src/a.txt'], self.allowed)

    def test_sed_in_place_in_any_position_writes_its_file_operands(self):
        self.each(["sed -E -i 's/a/b/' other.txt", "sed -e 's/a/b/' -i other.txt", "sed -i.bak 's/a/b/' other.txt", "sed --in-place 's/a/b/' other.txt",
                   "sed -n -i -e 's/a/b/' other.txt README.md", "sed -Ei 's/a/b/' other.txt"], self.blocked)
        self.each(["sed -n 1p README.md", "sed -i 's/a/b/' src/a.txt", "sed -E -i 's/a/b/' src/a.txt", "sed -e 's/a/b/' README.md"], self.allowed)

    def test_powershell_clear_content_and_new_item_force_name_their_path(self):
        self.each(['Clear-Content other.txt', 'New-Item -ItemType File -Force other.txt', 'New-Item -Force -ItemType File -Path other.txt'], self.blocked, tool='PowerShell')
        self.each(['Clear-Content src/a.txt', 'New-Item -ItemType File -Force src/a.txt', 'Set-Content src/a.txt x', 'Get-Content README.md'], self.allowed, tool='PowerShell')


class RemoveRecursiveForce(GitGuardBase):
    def test_rm_recursive_and_force_in_any_spelling_is_refused(self):
        self.old = False                                       # the new export no longer relies on the substring rule alone
        self.each(['rm -rf src/a.txt', 'rm -fr src/a.txt', 'rm -r -f src/a.txt', 'rm -Rf src/a.txt', 'rm --recursive --force src/a.txt', 'rm -f -R src/a.txt',
                   'sudo rm -fR src/a.txt', 'bash -c "rm -r -f src/a.txt"'], self.blocked)

    def test_plain_rm_of_an_owned_file_stays_allowed(self):
        self.each(['rm src/a.txt', 'rm -f src/a.txt', 'rm -r src/a.txt', 'git commit -m "rm notes"'], self.allowed)

    def test_plain_rm_outside_owned_is_still_refused_by_the_path_rule(self):
        self.blocked('rm other.txt')


class Round2Wrappers(GitGuardBase):
    """Revision 2 (#12 review P1-1): git is found behind shell keywords, brackets, wrappers with their flags, eval, cmd /c, powershell -Command, wsl, and `\\` line joins."""
    def test_git_after_shell_keywords_and_brackets(self):
        self.each(['if ! git diff --quiet; then git stash; fi', 'for f in other.txt; do git checkout -- "$f"; done', 'if true; then :; else git restore .; fi',
                   '! git stash', '( git stash )', '{ git stash; }', 'while true; do git stash; done'], self.blocked)
        self.each(['if true; then git status; fi', '( git status )', 'if true; then git checkout -- src/a.txt; fi'], self.allowed)

    def test_git_after_wrappers_with_their_flags(self):
        self.each(['env -i git stash', 'sudo -E git stash', 'timeout 60 git stash', 'nice -n 5 git checkout -- other.txt', 'sudo -u root git restore other.txt',
                   'eval git stash', 'wsl git stash', 'wsl -e git stash'], self.blocked)
        self.each(['timeout 60 git status', 'nice -n 5 git checkout -- src/a.txt', 'env -i git diff'], self.allowed)

    def test_cmd_and_powershell_command_forms(self):
        for command in ('cmd /c git stash', 'powershell -Command git stash', 'pwsh -NoProfile -Command git restore other.txt'):
            with self.subTest(command=command): self.blocked(command, 'PowerShell')
        self.allowed('cmd /c git status', 'PowerShell')

    def test_a_backslash_line_end_joins_the_command(self):
        self.each(['git \\\nstash', 'git \\\n  checkout -- other.txt'], self.blocked)
        self.allowed('git \\\n  status')


class Round2Fed(GitGuardBase):
    def test_paths_that_arrive_through_xargs_or_find_exec_are_refused(self):
        self.each(['git diff --name-only | xargs git restore', 'git ls-files -m | xargs -n1 git checkout --', 'echo other.txt | xargs git checkout --',
                   'find . -name other.txt -exec git checkout -- {} +', 'find . -exec git restore {} \\;'], self.blocked)

    def test_xargs_with_a_harmless_command_stays_allowed(self):
        self.each(['git ls-files | xargs cat', 'git diff --name-only | xargs git add', 'find . -name "*.py" -exec cat {} +'], self.allowed)

    def test_stash_save_is_always_refused_and_push_with_owned_paths_allowed(self):
        self.each(['git stash save src/a.txt', 'git stash save -- src/a.txt', 'git stash save'], self.blocked, way_out=True)
        self.each(['git stash push -- src/a.txt', 'git stash -- src/a.txt'], self.allowed)


class Round2Words(GitGuardBase):
    def test_a_quoted_temp_variable_with_dotdot_outside_the_quotes_escapes_nothing(self):
        self.each(['echo x > "$TMPDIR"/../other.txt', 'cp README.md "$TEMP"/../x.txt', 'rm -r "$TMPDIR"/..', 'echo x > "${TMPDIR}"/../../other.txt'], self.blocked)
        self.allowed('echo x > "$TMPDIR"/f.txt')

    def test_a_longer_variable_name_is_not_the_temp_folder(self):
        self.each(['echo x > $TEMPDIR_X/other.txt', 'echo x > $TMPDIR_OLD/f'], self.blocked)
        self.each(['echo x > $TMPDIR/f.txt', 'echo x > ${TMPDIR}/f.txt'], self.allowed)

    def test_duplicating_a_stream_is_no_file(self):
        self.each(['echo error >&2; exit 1', 'out=$(git status 2>&1); echo "$out"', 'x=$(git rev-parse HEAD 2>&1)', 'git log 2>&1|head -5', '(echo err >&2)',
                   'git stash list >&2;'], self.allowed)
        self.each(['$out = git log -1 2>&1; $out', 'git rev-parse HEAD 2>&1;'], self.allowed, tool='PowerShell')
        self.blocked('echo x >& other.txt')

    def test_the_stream_number_before_a_redirect_is_not_a_sed_file(self):
        self.allowed("sed -i 's/a/b/' src/a.txt 2>/dev/null")
        self.blocked("sed -i 's/a/b/' other.txt 2>/dev/null")


class Round2Heredoc(GitGuardBase):
    def test_a_heredoc_body_is_text(self):
        self.each(["cat > src/a.txt <<'EOF'\nTo undo a change:\ngit checkout -- other.txt\nEOF",
                   "git commit -F - <<'EOF'\nhook: refuse discards\n\ngit stash is refused now\nEOF",
                   "git commit -m \"$(cat <<'EOF'\nhook: refuse discards\n\ngit checkout -- . is refused\nEOF\n)\"",
                   "cat > .onecrew/scratch/undo.sh <<'EOF'\ngit stash\nEOF", "cat <<-EOF > src/a.txt\n\tgit stash\n\tEOF"], self.allowed)

    def test_a_heredoc_that_feeds_a_shell_is_judged(self):
        self.each(["bash <<'EOF'\ngit stash\nEOF", "sh <<'EOF'\ngit checkout -- other.txt\nEOF"], self.blocked)

    def test_a_command_after_the_heredoc_is_still_judged(self):
        self.blocked("cat <<'EOF' > src/a.txt\ntext\nEOF\ngit stash")


class Round2Branch(GitGuardBase):
    def setUp(self):
        super().setUp()
        heads = self.repo / '.git' / 'refs' / 'heads'
        heads.mkdir(parents=True)
        (heads / 'docs').write_text('0' * 40 + '\n')
        (heads / 'feature').write_text('0' * 40 + '\n')
        (self.repo / 'docs').mkdir()
        (self.repo / 'docs' / 'n.md').write_text('n\n', encoding='utf-8')

    def test_a_branch_with_the_name_of_a_folder_is_a_branch_switch(self):
        self.each(['git checkout docs', 'git checkout feature', 'git checkout docs --'], self.allowed)

    def test_a_path_is_still_a_path(self):
        self.each(['git checkout -- docs', 'git checkout other.txt', 'git checkout feature other.txt'], self.blocked)

    def test_a_packed_branch_is_a_branch(self):
        (self.repo / '.git' / 'packed-refs').write_text('# pack-refs\n' + '0' * 40 + ' refs/heads/packed\n')
        (self.repo / 'packed').mkdir()
        self.allowed('git checkout packed')

    def test_the_branch_is_read_even_when_the_directory_is_unknown(self):
        self.allowed('cd "$CLAUDE_PROJECT_DIR" && git checkout feature')


if __name__ == '__main__':
    unittest.main()
