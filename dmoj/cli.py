import argparse
import os
import re
import sys
from collections import OrderedDict
from itertools import izip_longest
from operator import itemgetter
import difflib
import tempfile
import subprocess

import pygments
from pygments import lexers
from pygments import formatters

from dmoj import judgeenv
from dmoj.executors import executors
from dmoj.judge import Judge
from dmoj.utils.ansi import ansi_style


class LocalPacketManager(object):
    def __init__(self, judge):
        self.judge = judge

    def _receive_packet(self, packet):
        pass

    def supported_problems_packet(self, problems):
        pass

    def test_case_status_packet(self, position, result):
        pass

    def compile_error_packet(self, log):
        pass

    def compile_message_packet(self, log):
        pass

    def internal_error_packet(self, message):
        pass

    def begin_grading_packet(self, is_pretested):
        pass

    def grading_end_packet(self):
        pass

    def batch_begin_packet(self):
        pass

    def batch_end_packet(self):
        pass

    def current_submission_packet(self):
        pass

    def submission_terminated_packet(self):
        pass

    def submission_acknowledged_packet(self, sub_id):
        pass

    def run(self):
        pass


class LocalJudge(Judge):
    def __init__(self):
        self.packet_manager = LocalPacketManager(self)
        super(LocalJudge, self).__init__()


commands = OrderedDict()


def register(command):
    commands[command.name] = command


class InvalidCommandException(Exception):
    pass


class CommandArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        raise InvalidCommandException

    def exit(self, status=0, message=None):
        if message:
            self._print_message(message, sys.stderr)
        raise InvalidCommandException


class Command(object):
    name = 'command'
    help = ''

    def __init__(self, judge):
        self.judge = judge
        self.arg_parser = CommandArgumentParser(prog=self.name, description=self.help)
        self._populate_parser()

    def _populate_parser(self):
        pass

    def execute(self, line):
        raise NotImplementedError


class ListProblemsCommand(Command):
    name = 'problems'
    help = 'Lists the problems available to be graded on this judge.'

    def _populate_parser(self):
        self.arg_parser.add_argument('filter', nargs='?', help='regex filter for problem names (optional)')
        self.arg_parser.add_argument('-l', '--limit', type=int, help='limit number of results', metavar='<limit>')

    def execute(self, line):
        _args = self.arg_parser.parse_args(line)

        if _args.limit is not None and _args.limit <= 0:
            print ansi_style("#ansi[--limit must be >= 0](red|bold)\n")
            return

        all_problems = judgeenv.get_supported_problems()

        if _args.filter:
            r = re.compile(_args.filter)
            all_problems = filter(lambda x: r.match(x[0]) is not None, all_problems)

        if _args.limit:
            all_problems = all_problems[:_args.limit]

        if len(all_problems):
            problems = iter(map(itemgetter(0), all_problems))
            max_len = max(len(p[0]) for p in all_problems)
            for row in izip_longest(*[problems] * 4, fillvalue=''):
                print ' '.join(('%*s' % (-max_len, row[i])) for i in xrange(4))
        else:
            print ansi_style("#ansi[No problems matching filter found.](red|bold)")
        print


class QuitCommand(Command):
    name = 'quit'
    help = 'Exits the DMOJ command-line interface.'

    def execute(self, line):
        sys.exit(0)


class HelpCommand(Command):
    name = 'help'
    help = 'Prints listing of commands.'

    def execute(self, line):
        print "Run `command -h/--help` for individual command usage."
        for name, command in commands.iteritems():
            if command == self:
                continue
            print '  %s: %s' % (name, command.help)
        print


submission_id_counter = 0
graded_submissions = []


class SubmitCommand(Command):
    name = 'submit'
    help = 'Grades a submission.'

    def _populate_parser(self):
        self.arg_parser.add_argument('problem_id', help='id of problem to grade')
        self.arg_parser.add_argument('source_file', nargs='?', help='path to submission source (optional)')
        self.arg_parser.add_argument('-lan', '--language-id', type=str, default=' ', help='id of the language to grade in (e.g., PY2)')
        self.arg_parser.add_argument('-tl', '--time-limit', type=float, help='time limit for grading, in seconds',
                                     default=2.0, metavar='<time limit>')
        self.arg_parser.add_argument('-ml', '--memory-limit', type=int, help='memory limit for grading, in kilobytes',
                                     default=65536, metavar='<memory limit>')

    def execute(self, line):
        global submission_id_counter, graded_submissions

        args = self.arg_parser.parse_args(line)

        problem_id = args.problem_id
        time_limit = args.time_limit
        memory_limit = args.memory_limit
        language_id = args.language_id

        err = None

        if problem_id not in map(itemgetter(0), judgeenv.get_supported_problems()):
            err = "unknown problem '%s'" % problem_id
        elif language_id == ' ':
            if args.source_file:
                ext = None
                try:
                    filename, ext = args.source_file.split('.')
                except:
                    err = 'invalid file'
                ext = ext.upper()
                print ext
                if ext == 'PY':
                    language_id = 'PY2'
                elif ext == 'CPP':
                    language_id = 'CPP14'
                elif ext == 'JAVA':
                    language_id = 'JAVA9'
                elif ext:
                    language_id = ext
                else:
                    err = "unknown language '%s'" % language_id
            else:
                err = "no language is selected"
        elif language_id not in executors:
            err = "unknown language '%s'" % language_id
        elif time_limit <= 0:
            err = '--time-limit must be >= 0'
        elif memory_limit <= 0:
            err = '--memory-limit must be >= 0'
        if not err:
            if args.source_file:
                try:
                    with open(os.path.realpath(args.source_file), 'r') as f:
                        src = f.read()
                except Exception as io:
                    err = str(io)
            else:
                file_suffix = '.' + language_id
                try:
                    with tempfile.NamedTemporaryFile(suffix=file_suffix) as temp:
                        subprocess.call(['nano', temp.name])
                        temp.seek(0)
                        src = temp.read()
                        temp.close()
                except Exception:
                    for warning in judgeenv.startup_warnings:
                        print ansi_style('#ansi[Warning: %s](yellow)' % warning)

        if err:
            print ansi_style('#ansi[%s](red|bold)\n' % err)
            return

        submission_id_counter += 1
        graded_submissions.append((problem_id, language_id, src, time_limit, memory_limit))
        self.judge.begin_grading(submission_id_counter, problem_id, language_id, src, time_limit,
                                 memory_limit, False, False, blocking=True)


class ResubmitCommand(Command):
    name = 'resubmit'
    help = 'Resubmit a submission with different parameters.'

    def _populate_parser(self):
        self.arg_parser.add_argument('submission_id', type=int, help='id of submission to resubmit')
        self.arg_parser.add_argument('-p', '--problem', help='id of problem to grade', metavar='<problem id>')
        self.arg_parser.add_argument('-l', '--language', help='id of the language to grade in (e.g., PY2)',
                                     metavar='<language id>')
        self.arg_parser.add_argument('-tl', '--time-limit', type=float, help='time limit for grading, in seconds',
                                     metavar='<time limit>')
        self.arg_parser.add_argument('-ml', '--memory-limit', type=int, help='memory limit for grading, in kilobytes',
                                     metavar='<memory limit>')

    def execute(self, line):
        global submission_id_counter, graded_submissions

        args = self.arg_parser.parse_args(line)

        submission_id_counter += 1
        try:
            id, lang, src, tl, ml = graded_submissions[args.submission_id - 1]
        except IndexError:
            print ansi_style("#ansi[invalid submission '%d'](red|bold)\n" % (args.submission_id - 1))
            return

        id = args.problem or id
        lang = args.language or lang
        tl = args.time_limit or tl
        ml = args.memory_limit or ml

        err = None
        if id not in map(itemgetter(0), judgeenv.get_supported_problems()):
            err = "unknown problem '%s'" % id
        elif lang not in executors:
            err = "unknown language '%s'" % lang
        elif tl <= 0:
            err = '--time-limit must be >= 0'
        elif ml <= 0:
            err = '--memory-limit must be >= 0'
        if err:
            print ansi_style('#ansi[%s](red|bold)\n' % err)
            return

        try:
            with tempfile.NamedTemporaryFile() as temp:
                temp.write('%s' % src)
                temp.flush()
                subprocess.call(['nano', temp.name])
                temp.seek(0)
                src = temp.read()
                temp.close()
        except Exception:
            for warning in judgeenv.startup_warnings:
                print ansi_style('#ansi[Warning: %s](yellow)' % warning)

        graded_submissions.append((id, lang, src, tl, ml))
        self.judge.begin_grading(submission_id_counter, id, lang, src, tl, ml, False, False, blocking=True)


class RejudgeCommand(Command):
    name = 'rejudge'
    help = 'Rejudge a submission.'

    def _populate_parser(self):
        self.arg_parser.add_argument('submission_id', type=int, help='id of submission to rejudge')

    def execute(self, line):
        global graded_submissions

        args = self.arg_parser.parse_args(line)
        try:
            problem, lang, src, tl, ml = graded_submissions[args.submission_id - 1]
        except IndexError:
            print ansi_style("#ansi[invalid submission '%d'](red|bold)\n" % (args.submission_id - 1))
            return
        self.judge.begin_grading(submission_id_counter, problem, lang, src, tl, ml, False, False, blocking=True)


class ListSubmissionsCommand(Command):
    name = 'submissions'
    help = 'List past submissions.'

    def _populate_parser(self):
        self.arg_parser.add_argument('-l', '--limit', type=int, help='limit number of results by most recent',
                                     metavar='<limit>')

    def execute(self, line):
        args = self.arg_parser.parse_args(line)

        if args.limit is not None and args.limit <= 0:
            print ansi_style('#ansi[--limit must be >= 0](red|bold)\n')
            return

        for i, data in enumerate(
                graded_submissions if not args.limit else graded_submissions[:args.limit]):
            problem, lang, src, tl, ml = data
            print ansi_style('#ansi[%s](yellow)/#ansi[%s](green) in %s' % (problem, i + 1, lang))
        print
        

class DifferenceCommand(Command):
    name = 'diff'
    help = 'Shows difference between two files.'

    def _populate_parser(self):
        self.arg_parser.add_argument('id_or_source_1', help='id or path of first source', metavar='<source 1>')
        self.arg_parser.add_argument('id_or_source_2', help='id or path of second source', metavar='<source 2>')

    def get_data(self, id_or_source):
        err = None
        src = None
        try:
            id = int(id_or_source)
            try:
                global graded_submissions
                problem, lang, src, tl, ml = graded_submissions[id - 1]
            except IndexError:
                err = "invalid submission '%d'" % (id - 1)
        except ValueError:
            try:
                with open(os.path.realpath(id_or_source), 'r') as f:
                    src = f.read()
            except Exception as io:
                 err = str(io)

        return src, err

    def execute(self, line):
        args = self.arg_parser.parse_args(line)

        data1, err1 = self.get_data(args.id_or_source_1)
        data2, err2 = self.get_data(args.id_or_source_2)

        file1 = args.id_or_source_1
        file2 = args.id_or_source_2

        difference = difflib.unified_diff(data1.splitlines(), data2.splitlines(), fromfile=file1, tofile=file2, lineterm='')
        file_diff = '\n'.join(list(difference))
        print pygments.highlight(file_diff, pygments.lexers.DiffLexer(), pygments.formatters.Terminal256Formatter())

class ShowSubmissonIdOrFilename(Command):
    name = 'show'
    help = 'Shows file based on submission ID or filename.'

    def _populate_parser(self):
        self.arg_parser.add_argument('id_or_source', help='id or path of submission to show', metavar='<source>')

    def get_data(self, id_or_source):
        err = None
        src = None
        lexer = None
        try:
            id = int(id_or_source)
            try:
                global graded_submissions
                problem, lang, src, tl, ml = graded_submissions[id - 1]
                if lang in ['PY2', 'PYPY2']:
                    lexer = pygments.lexers.PythonLexer()
                elif lang in ['PY3', 'PYPY3']:
                    lexer = pygments.lexers.Python3Lexer()
                else:
                    lexer = pygments.lexers.guess_lexer(src)
            except IndexError:
                err = "invalid submission '%d'" % (id - 1)
        except ValueError:
            try:
                with open(os.path.realpath(id_or_source), 'r') as f:
                    src = f.read()
                    lexer = pygments.lexers.guess_lexer_for_file(id_or_source, src)
            except Exception as io:
                err = str(io)

        return src, err, lexer

    def execute(self, line):
        args = self.arg_parser.parse_args(line)
        data, err, lexer = self.get_data(args.id_or_source)

        print pygments.highlight(data, lexer, pygments.formatters.Terminal256Formatter())


def main():
    global commands
    import logging
    from dmoj import judgeenv, executors

    judgeenv.load_env(cli=True)

    # Emulate ANSI colors with colorama
    if os.name == 'nt' and not judgeenv.no_ansi_emu:
        try:
            from colorama import init
            init()
        except ImportError:
            pass

    executors.load_executors()

    print 'Running local judge...'

    logging.basicConfig(filename=judgeenv.log_file, level=logging.INFO,
                        format='%(levelname)s %(asctime)s %(module)s %(message)s')

    judge = LocalJudge()

    for warning in judgeenv.startup_warnings:
        print ansi_style('#ansi[Warning: %s](yellow)' % warning)
    del judgeenv.startup_warnings
    print

    for command in [ListProblemsCommand, ListSubmissionsCommand, SubmitCommand, ResubmitCommand, RejudgeCommand,
                    HelpCommand, QuitCommand, DifferenceCommand, ShowSubmissonIdOrFilename]:
        register(command(judge))

    with judge:
        try:
            judge.listen()

            while True:
                command = raw_input(ansi_style("#ansi[dmoj](magenta)#ansi[>](green) ")).strip()

                line = command.split(' ')
                if line[0] in commands:
                    cmd = commands[line[0]]
                    try:
                        cmd.execute(line[1:])
                    except InvalidCommandException:
                        print
                else:
                    print ansi_style('#ansi[Unrecognized command %s](red|bold)' % line[0])
                    print
        except (EOFError, KeyboardInterrupt):
            print
        finally:
            judge.murder()


if __name__ == '__main__':
    sys.exit(main())
