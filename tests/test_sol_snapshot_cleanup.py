import unittest
from onecrew.v2.verifiers import command


class SnapshotPipeTests(unittest.TestCase):
    def test_failed_stdin_write_closes_the_owned_pipe(self):
        class Pipe:
            closed = False
            def write(self, data): raise BrokenPipeError('terminated fixture git')
            def close(self): self.closed = True
        pipe = Pipe()
        command._feed(pipe, b'fixture input')
        self.assertTrue(pipe.closed)
