class ProgramTerminated(Exception):
    """Raised in place of the VBA `TerminateProgram` sub.

    The VBA version showed a MsgBox and then called `End`, which killed the whole
    Excel macro. Here we just raise, so callers (a CLI, a script, a test) decide
    what "terminate" means for them.
    """
