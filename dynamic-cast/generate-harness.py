#!/usr/bin/env python3

import argparse
import random

DEBUG = False
MSVC = False

class Subobject(object):
    def __init__(self, base, is_virtual, offset, direct_subobject_of):
        self.base = base
        self.is_virtual = is_virtual
        self.offset = offset
        self.direct_subobject_of = direct_subobject_of
        self.direct_superobject_of = []

    def has_public_path_down_to(self, root):
        if self == root:
            return True
        for dso in self.direct_subobject_of:
            if dso.base.has_direct_public_base(self.base):
                if dso.has_public_path_down_to(root):
                    return True
        return False


class LayoutState(object):
    def __init__(self, root):
        self.root_class = root
        self.root_subobject = Subobject(base=self.root_class, is_virtual=False, offset=0, direct_subobject_of=[])
        self.layout = [self.root_subobject]
        self.offset = 0
        self.public_child_pairs = set()
        self.ambiguous_public_child_pairs = set()

    def populate_superobjects(self):
        for p in self.layout:
            for c in p.direct_subobject_of:
                c.direct_superobject_of += [p]
        for p in self.layout:
            p.direct_superobject_of = sorted(p.direct_superobject_of, key=lambda so: p.base.inheritance_order_of(so.base))

    def print_layout(self):
        for so in self.layout:
            print('%3d: %s%s' % (so.offset, so.base.name, ' (virtual)' if so.is_virtual else ''))
            for dso in so.direct_subobject_of:
                print('  direct subobject of %s (%d)' % (dso.base.name, dso.offset))


class Node(object):
    def __init__(self, name):
        self.name = name
        self.direct_bases = []
        self.state = None

    def has_ancestor(self, base):
        if self == base:
            return True
        return any(b.base.has_ancestor(base) for b in self.direct_bases)

    def maybe_add_base(self, base, is_virtual, is_public):
        if all(b.base != base for b in self.direct_bases):
            newedge = Edge(base, is_virtual, is_public)
            self.direct_bases += [newedge]

    def inheritance_order_of(self, base):
        for i, b in enumerate(self.direct_bases):
            if b.base == base:
                return i
        return None

    def get_all_virtual_bases(self, acc):
        for b in self.direct_bases:
            if MSVC:
                acc = b.base.get_all_virtual_bases(acc)
            if b.is_virtual and b.base not in acc:
                acc += [b.base]
            if not MSVC:
                acc = b.base.get_all_virtual_bases(acc)
        return acc

    def has_direct_public_base(self, base):
        return any(b.base == base for b in self.direct_bases if b.is_public)

    def has_direct_virtual_base(self, base):
        return any(b.base == base for b in self.direct_bases if b.is_virtual)

    def is_ambiguous_base(self, base):
        return len([so for so in self.get_class_layout() if so.base == base]) >= 2

    def has_any_virtual_bases(self):
        return bool(self.get_all_virtual_bases([]))

    def layout_(self, state, from_subobject, include_virtual_bases):
        for b in self.direct_bases:
            if not b.is_virtual:
                so = Subobject(b.base, is_virtual=False, offset=state.offset, direct_subobject_of=[from_subobject])
                state.layout += [so]
                so.base.layout_(state, from_subobject=so, include_virtual_bases=False)

        if not MSVC:
            if all(b.is_virtual for b in self.direct_bases):
                state.offset += 8  # for my vptr, since I have no non-virtual direct bases
            state.offset += 8  # for my data
        else:
            if not self.direct_bases:
                state.offset += 8  # for my vfptr
            if any(b.is_virtual for b in self.direct_bases):
                if not any(b.base.has_any_virtual_bases() for b in self.direct_bases if not b.is_virtual):
                    state.offset += 8  # for my vbptr
            state.offset += 8  # for my data

        if include_virtual_bases:
            for base in self.get_all_virtual_bases([]):
                so = Subobject(base, is_virtual=True, offset=state.offset, direct_subobject_of=[])
                state.layout += [so]
                so.base.layout_(state, from_subobject=so, include_virtual_bases=False)
            for parentso in state.layout[1:]:
                if parentso.is_virtual:
                    for childso in state.layout:
                        if childso.base.has_direct_virtual_base(parentso.base):
                            parentso.direct_subobject_of += [childso]
        return

    def generate_base_paths(self, acc, f):
        yield acc
        for b in self.direct_bases:
            if self.is_ambiguous_base(b.base):
                continue
            for p in b.base.generate_base_paths(acc + f(b), f):
                yield p

    def get_class_layout(self):
        state = self.get_populated_layout_state()
        return state.layout

    def get_full_object_size(self):
        state = self.get_populated_layout_state()
        return state.offset

    def get_public_bases(self):
        state = self.get_populated_layout_state()
        for so in state.layout[1:]:
            if so.has_public_path_down_to(state.root_subobject):
                yield so

    def get_nonpublic_bases(self):
        state = self.get_populated_layout_state()
        for so in state.layout[1:]:
            if not so.has_public_path_down_to(state.root_subobject):
                yield so

    def get_unambiguous_public_bases(self):
        for so in self.get_public_bases():
            if not self.is_ambiguous_base(so.base):
                yield so

    def get_populated_layout_state(self):
        global DEBUG
        if self.state is None:
            if False: DEBUG=True
            state = LayoutState(self)
            self.layout_(state, from_subobject=state.layout[0], include_virtual_bases=True)
            if DEBUG: state.print_layout()

            state.populate_superobjects()

            state.public_child_pairs = set()
            for p in state.layout[1:]:
                for c in state.layout[1:]:
                    # Notice it is possible for p (the more-leaflike of the two) to be laid out
                    # physically-before some of p's children if those children are themselves virtual.
                    pc = (p, c)
                    if p != c and p.has_public_path_down_to(c):
                        state.public_child_pairs.add(pc)

            state.ambiguous_public_child_pairs = set()
            for (parent, child) in state.public_child_pairs:
                descendants_of_child_type = sum(1 for p, c in state.public_child_pairs if p == parent and c.base == child.base)
                if descendants_of_child_type >= 2:
                    state.ambiguous_public_child_pairs.add((parent, child))
            self.state = state
            DEBUG=False
        return self.state

    def get_public_child_pairs(self):
        state = self.get_populated_layout_state()
        return sorted(state.public_child_pairs - state.ambiguous_public_child_pairs,
                      key=lambda pc: (pc[0].base.name, pc[0].offset, pc[1].base.name, pc[1].offset))

class Edge(object):
    def __init__(self, base, is_virtual, is_public):
        self.base = base
        self.is_virtual = is_virtual
        self.is_public = is_public

    def to_string(self):
        return '%s%s%s' % (
            'public ' if self.is_public else 'protected ',
            'virtual ' if self.is_virtual else '',
            self.base.name,
        )


def tf():
    return random.choice([True, False])


def populate():
    nodes = []
    for i in range(10):
        newclass = Node('Class%d' % (i + 1))
        if i >= 3:
            for j in range(3):
                if nodes:
                    newclass.maybe_add_base(random.choice(nodes), is_virtual=tf(), is_public=tf())
        nodes += [newclass]
    return nodes


def class_definition(node):
    def as_foo(name):
        return '%s *as_%s() { return this; }' % (name, name)

    result = '''
struct %s %s %s {
    void *%sdata;
    char *as_charptr() { return (char*)this; }
    %s
    %s
    virtual ~%s() {}
};
    '''.strip() % (
        node.name,
        ':' if node.direct_bases else '',
        ', '.join(b.to_string() for b in node.direct_bases),
        node.name,
        '\n    '.join(as_foo(b.base.name) for b in node.direct_bases if not node.is_ambiguous_base(b.base)),
        as_foo(node.name),
        node.name,
    ) + '\n'
    result += '''
static_assert(sizeof (%s) == %d%s);
    '''.strip() % (
        node.name,
        node.get_full_object_size(),
        ', "unexpected sizeof"' if MSVC else '',
    ) + '\n'
    return result


def typeinfo_definition(node):
    result = '''
void *%s_convertToBase(char *p, const std::type_info& to) {%s
    return nullptr;
}
    '''.strip() % (
        node.name,
        ''.join(
            '\n    if (to == typeid(%s)) return p + %d;' % (so.base.name, so.offset)
            for so in node.get_unambiguous_public_bases()
        ),
    ) + '\n'
    result += '''
void *%s_maybeFromHasAPublicChildOfTypeTo(char *p, int offset, const std::type_info& from, const std::type_info& to) {%s
    return nullptr;
}
    '''.strip() % (
        node.name,
        ''.join(
            '\n    if (from == typeid(%s) && to == typeid(%s) && offset == %d) return p + %d;' % (f.base.name, t.base.name, f.offset, t.offset)
            for f, t in node.get_public_child_pairs()
        ),
    ) + '\n'
    result += '''
bool %s_isPublicBaseOfYourself(int offset, const std::type_info& from) {%s%s
    printf("unexpectedly %%d %%s\\n", offset, from.name());
    assert(false);
    return false;
}
    '''.strip() % (
        node.name,
        ''.join(
            '\n    if (from == typeid(%s) && offset == %d) return true;' % (so.base.name, so.offset)
            for so in node.get_public_bases()
        ),
        ''.join(
            '\n    if (from == typeid(%s) && offset == %d) return false;' % (so.base.name, so.offset)
            for so in node.get_nonpublic_bases()
        ),
    ) + '\n'
    result += '''
MyTypeInfo %s_typeinfo {
    %s_convertToBase,
    %s_maybeFromHasAPublicChildOfTypeTo,
    %s_isPublicBaseOfYourself,
};
    '''.strip() % (
        node.name,
        node.name,
        node.name,
        node.name,
    ) + '\n'
    return result


def dispatcher_definition(nodes):
    return '''
const MyTypeInfo& awkward_typeinfo_conversion(const std::type_info& ti) {%s
    assert(false);
}
    '''.strip() % (
        ''.join(
            '\n    if (ti == typeid(%s)) return %s_typeinfo;' % (n.name, n.name)
            for n in nodes
        )
    )


def help_msvc_with_sfinae(nodes):
    result = ''
    for f in nodes:
        result += 'template<> struct can_dynamic_cast<%s*, void*> : std::true_type {};\n' % f.name
        for t in nodes:
            if f == t:
                can_dynamic_cast = True
            elif f.is_ambiguous_base(t):
                can_dynamic_cast = False
            elif any(so.base == t for so in f.get_public_bases()):
                can_dynamic_cast = True
            elif any(so.base == t for so in f.get_nonpublic_bases()):
                can_dynamic_cast = False
            else:
                can_dynamic_cast = True
            result += 'template<> struct can_dynamic_cast<%s*, %s*> : std::%s {};\n' % (
                f.name,
                t.name,
                'true_type' if can_dynamic_cast else 'false_type',
            )
    return result


def test_to_function_definition(nodes):
    result = '''
template<class To>
void test_to() {
    '''.strip() + '\n'
    for n in nodes:
        for path in n.generate_base_paths('instance<%s>()' % n.name, lambda b: '->as_%s()' % b.base.name):
            result += '    test<To>(can_dynamic_cast<decltype(%s),To*>{}, %s, instance<%s>()->as_charptr(), "%s");\n' % (path, path, n.name, path)

    result += '}\n'
    return result


def test_main_function_definition(nodes):
    return '''
int main() {
    test_to<void>();
%s
    printf("%%d failures.\\n", failure_count());
    return failure_count() ? 1 : 0;
}
    '''.strip() % (
        '\n'.join('    test_to<%s>();' % n.name for n in nodes)
    )


def benchmark_to_function_definition(nodes):
    result = '''
template<class To, class Native>
void benchmark_to(Native n) {
    '''.strip() + '\n'
    for n in nodes:
        for path in n.generate_base_paths('instance<%s>()' % n.name, lambda b: '->as_%s()' % b.base.name):
            result += '    run_benchmark<To>(n, %s);\n' % (path)

    result += '}\n'
    return result


def benchmark_main_function_definition(nodes):
    return '''
TEST(void)
%s
BENCHMARK_MAIN();
    '''.strip() % (
        '\n'.join('TEST(%s)' % n.name for n in nodes)
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=None, help='Seed for the random number generator')
    parser.add_argument('--benchmark', action='store_true', help='Generate a benchmark harness instead of a testing harness')
    parser.add_argument('--msvc', action='store_true', help='Use MSVC ABI instead of Itanium ABI')
    options = parser.parse_args()
    MSVC = options.msvc

    random.seed(options.seed)

    nodes = populate()
    with open('things.gen.h', 'w') as things_h:
        for n in nodes:
            print(class_definition(n), file=things_h)
    with open('things.gen.cc', 'w') as things_cc:
        print('#include "things.gen.h"', file=things_cc)
        print('#include "dynamicast.h"', file=things_cc)
        print('#include <cassert>', file=things_cc)
        print('#include <cstdio>', file=things_cc)
        print('#include <typeinfo>\n', file=things_cc)
        for n in nodes:
            print(typeinfo_definition(n), file=things_cc)
        print(dispatcher_definition(nodes), file=things_cc)
    with open('harness.gen.cc', 'w') as harness_cc:
        print('#include "things.gen.h"', file=harness_cc)
        print('#include "dynamicast.h"', file=harness_cc)
        if options.benchmark:
            print('#include "benchmark-harness.h"\n', file=harness_cc)
            if MSVC:
                print(help_msvc_with_sfinae(nodes), file=harness_cc)
            print(benchmark_to_function_definition(nodes), file=harness_cc)
            print(benchmark_main_function_definition(nodes), file=harness_cc)
        else:
            print('#include "test-harness.h"\n', file=harness_cc)
            if MSVC:
                print(help_msvc_with_sfinae(nodes), file=harness_cc)
            print(test_to_function_definition(nodes), file=harness_cc)
            print(test_main_function_definition(nodes), file=harness_cc)
