#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import itertools


def do_gcc_and_clang(seed):
    failed = []
    try:
        subprocess.check_call([
            sys.executable, 'generate-harness.py', '--seed', str(seed),
        ], stdout=dev_null)
        try:
            subprocess.check_call([
                '../dependency-graph/unity-dump.py',
                'things.gen.cc', 'dynamicast.cc', 'harness.gen.cc',
                '--g++',
            ], stdout=dev_null, stderr=dev_null, env=gcc_env)
            print('.', end='', file=sys.stderr)
        except subprocess.CalledProcessError:
            failed += ['gcc']
        try:
            subprocess.check_call([
                '../dependency-graph/unity-dump.py',
                'things.gen.cc', 'dynamicast.cc', 'harness.gen.cc',
                '--clang'
            ], stdout=dev_null, stderr=dev_null, env=gcc_env)
            print('.', end='', file=sys.stderr)
        except subprocess.CalledProcessError:
            failed += ['clang']
    except subprocess.CalledProcessError:
        failed += ['generator']
    return failed


def do_msvc(seed):
    failed = []
    try:
        subprocess.check_call([
            sys.executable, 'generate-harness.py', '--seed', str(seed), '--msvc',
        ], stdout=dev_null)
        try:
            subprocess.check_call([
                '../dependency-graph/unity-dump.py',
                'things.gen.cc', 'dynamicast.cc', 'harness.gen.cc',
                '--msvc'
            ], stdout=dev_null, stderr=dev_null)
            print('.', end='', file=sys.stderr)
        except subprocess.CalledProcessError:
            failed += ['msvc']
    except subprocess.CalledProcessError:
        failed += ['msvc-generator']
    return failed


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=1, help='Initial seed (and we count upward from there)')
    options = parser.parse_args()

    dev_null = open('/dev/null', 'w')
    gcc_env = os.environ.copy()
    gcc_env['CXXFLAGS'] = '-DFREE_USE_OF_CXX17'

    # Use an effectively unbounded counter starting at options.seed
    for i in itertools.count(options.seed):
        failed = []
        failed += do_gcc_and_clang(i)
        failed += do_msvc(i)
        if failed:
            print('{}: {}'.format('+'.join(failed), i))

