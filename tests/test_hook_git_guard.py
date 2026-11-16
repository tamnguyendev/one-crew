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


if __name__ == '__main__':
    unittest.main()
