"""Static analysis and decoration of flow-kit html blocks for visualize-changes.

An html block is parsed into a small element tree. From it the builder learns which branches end the flow and
which continue, and which steps carry conditions, so the page can draw the difference and the build can warn.
"""
import html
import re
from html.parser import HTMLParser

VOID = {"br", "hr", "img", "input", "meta", "link", "wbr"}
CONDITIONAL_TEXT = re.compile(r"^\s*(if|when|whenever|only if|skip if|unless|for condition)\b", re.IGNORECASE)
DETAIL_CONDITION = re.compile(r"^\s*(if|when|unless|only if)\s", re.IGNORECASE)
MAX_FORK_DEPTH = 2
STOP_WORDING = re.compile(r"^\s*(return|respond|reject|error|fail|abort|skip)\w*\b", re.IGNORECASE)
DIAMOND = '<svg class="vc-dia" viewBox="0 0 100 50" preserveAspectRatio="none" aria-hidden="true"><polygon points="50,1 99,25 50,49 1,25"/></svg>'
MAX_ASIDES = 4
ASIDES_INLINE = 2


class Node:
    def __init__(self, tag, cls, start, start_end, parent):
        self.tag, self.cls, self.start, self.start_end, self.parent = tag, cls, start, start_end, parent
        self.end = self.end_end = None
        self.children = []

    def has(self, name):
        return name in self.cls

    def kids(self, name):
        return [c for c in self.children if c.has(name)]


class Tree(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0]
        for line in source.split("\n"):
            self.lines.append(self.lines[-1] + len(line) + 1)
        self.root = Node("#root", [], 0, 0, None)
        self.cur = self.root
        self.nodes = []

    def here(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        start = self.here()
        text = self.get_starttag_text()
        cls = (dict(attrs).get("class") or "").split()
        node = Node(tag, cls, start, start + len(text), self.cur)
        self.cur.children.append(node)
        self.nodes.append(node)
        if tag not in VOID:
            self.cur = node
        else:
            node.end, node.end_end = node.start_end, node.start_end

    def handle_startendtag(self, tag, attrs):
        start = self.here()
        text = self.get_starttag_text()
        node = Node(tag, (dict(attrs).get("class") or "").split(), start, start + len(text), self.cur)
        node.end, node.end_end = node.start_end, node.start_end
        self.cur.children.append(node)
        self.nodes.append(node)

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is self.root:
            return
        node.end = self.here()
        node.end_end = self.source.find(">", node.end) + 1
        self.cur = node.parent

    def text(self, node):
        inner = self.source[node.start_end:node.end]
        return html.unescape(re.sub(r"<[^>]*>", " ", inner)).strip()

    def own_text(self, node):
        """Text before the first child element: the step's own line, not its detail."""
        stop = node.children[0].start if node.children else node.end
        return html.unescape(re.sub(r"<[^>]*>", " ", self.source[node.start_end:stop])).strip()


def last_element(flow):
    return flow.children[-1] if flow.children else None


def branch_ends(branch):
    """A branch ends the flow when its last step is a terminal pill, or its last child is a fork whose branches all end."""
    flow = next(iter(branch.kids("vc-flow")), None)
    last = last_element(flow) if flow else None
    if last is None:
        return False
    if last.has("vc-step") and last.has("term"):
        return True
    if last.has("vc-branches") and last.has("fork"):
        branches = last.kids("vc-branch")
        return bool(branches) and all(branch_ends(b) for b in branches)
    return False


def leaf_count(branch):
    """How many leaf branches sit under a branch: the widest fork nested in its flow, summed over that fork's branches."""
    best = 1
    for flow in branch.kids("vc-flow"):
        for fork in (c for c in flow.children if c.has("vc-branches") and c.has("fork")):
            best = max(best, sum(leaf_count(b) for b in fork.kids("vc-branch")))
    return best


def fork_depth(fork):
    depth, node = 1, fork.parent
    while node is not None:
        if node.has("vc-branches") and node.has("fork"):
            depth += 1
        node = node.parent
    return depth


def join_classes(ends):
    """Per branch, the classes of its join span: "v" draws the stub under a continuing branch, and "hl", "hr" or "hf" the
    part of the bar (left half, right half, whole) that lies under it. The bar links every continuing branch's center to
    the fork's center, where the arrow into the next step sits, so one lone continuing branch still reaches it. A branch
    that ends but lies between a continuing branch and the center carries the bar through without a stub."""
    n = len(ends)
    centers = [i + 0.5 for i, ended in enumerate(ends) if not ended]
    if not centers:
        return [""] * n
    left, right = min(min(centers), n / 2), max(max(centers), n / 2)
    out = []
    for i, ended in enumerate(ends):
        lo, hi = max(left, i), min(right, i + 1)
        span = hi - lo
        bar = "" if span <= 0 else "hf" if span >= 1 else "hl" if lo == i else "hr"
        out.append(" ".join(c for c in ("" if ended else "v", bar) if c))
    return out


def set_attr(tag, name, value, merge=False):
    """A start tag with attribute `name` set to value, whatever quoting the author used; merge appends to an existing one."""
    pat = re.compile(rf"""(?<=\s){name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.IGNORECASE)
    m = pat.search(tag)
    if m and merge:
        old = next(g for g in m.groups() if g is not None).strip().rstrip(";")
        value = f"{old}; {value}" if old else value
    attr = f'{name}="{value.replace(chr(34), "&quot;")}"'
    if m:
        return tag[:m.start()] + attr + tag[m.end():]
    end = len(tag) - (2 if tag.endswith("/>") else 1)
    return f"{tag[:end].rstrip()} {attr}{tag[end:]}"


def decorate(source, warn, where):
    """Return source with ends, joins, diamonds and folded asides drawn in; call warn(msg) for authoring problems."""
    tree = Tree(source)
    tree.feed(source)
    tree.close()
    adds = {}  # node -> classes to add
    styles = {}  # node id -> inline style to add
    inserts = []  # (offset, text), applied last-to-first

    def add_class(node, *names):
        adds.setdefault(id(node), (node, []))[1].extend(names)

    forks = [n for n in tree.nodes if n.has("vc-branches")]
    decisions = [n for n in tree.nodes if n.has("vc-decision")]
    if len(forks) > len(decisions):
        warn(f"{where}: {len(forks)} vc-branches but {len(decisions)} vc-decision; draw each condition as a diamond")
    for n in decisions:
        inserts.append((n.start_end, DIAMOND))

    for fork in (f for f in forks if f.has("fork")):
        branches = fork.kids("vc-branch")
        ends = [branch_ends(b) for b in branches]
        weights = [leaf_count(b) for b in branches]
        # Set on every fork, even with equal columns: a custom property is inherited, so a nested fork would otherwise
        # take its parent's column weights.
        styles[id(fork)] = "--cols:" + (" ".join(f"minmax(0,{w}fr)" for w in weights) if len(set(weights)) > 1 else "none")
        adds.setdefault(id(fork), (fork, []))
        if fork_depth(fork) > MAX_FORK_DEPTH:
            warn(f"{where}: forks nested {fork_depth(fork)} deep squeeze their branches; write a decision ladder instead "
                 "(each fork's non-ending branch continues to the next decision)")
        for b, ended in zip(branches, ends):
            flow = next(iter(b.kids("vc-flow")), None)
            last = last_element(flow) if flow else None
            if ended:
                add_class(b, "is-end")
                if last is not None and last.has("term"):
                    add_class(last, "end")
            else:
                add_class(b, "is-cont")
                if last is not None and last.has("vc-step") and not last.has("term") and STOP_WORDING.match(tree.own_text(last)):
                    warn(f"{where}: branch ends with {tree.own_text(last)!r}, which reads as a stop; end it with a term pill")
        cont = [b for b, ended in zip(branches, ends) if not ended]
        if not cont:
            add_class(fork, "all-end")
            siblings = fork.parent.children
            if fork.parent.has("vc-flow") and siblings.index(fork) < len(siblings) - 1:
                warn(f"{where}: every branch of a fork ends, but a step follows it; that step is unreachable")
        parent = fork.parent
        closes_flow = parent.has("vc-flow") and parent.children[-1] is fork and not (parent.parent and parent.parent.has("vc-branch"))
        if not closes_flow:
            for b, classes in zip(branches, join_classes(ends)):
                if classes:
                    inserts.append((b.end, f'<span class="vc-join {classes}" aria-hidden="true"></span>'))

    for step in (n for n in tree.nodes if n.has("vc-step")):
        asides = step.kids("vc-aside")
        if len(asides) > MAX_ASIDES:
            warn(f"{where}: a step carries {len(asides)} asides; move the extras to Failure models")
        if len(asides) > ASIDES_INLINE:
            hidden = len(asides) - ASIDES_INLINE
            inserts.append((asides[ASIDES_INLINE].start, f'<details class="vc-asides"><summary>{hidden} more condition{"s" if hidden > 1 else ""}</summary>'))
            inserts.append((asides[-1].end_end, "</details>"))
        text = tree.own_text(step)
        if CONDITIONAL_TEXT.match(text):
            warn(f"{where}: step {text!r} states a condition; draw it as a vc-decision with branches")
        for d in step.kids("vc-detail"):
            if DETAIL_CONDITION.match(tree.text(d)):
                warn(f"{where}: detail {tree.text(d)!r} reads as a condition; use a vc-aside")
    for t in (n for n in tree.nodes if n.has("vc-branch-title")):
        if CONDITIONAL_TEXT.match(tree.text(t)):
            warn(f"{where}: branch title {tree.text(t)!r} states a condition; put it in the vc-decision above")

    edits = list(inserts)
    for node, names in adds.values():
        tag = source[node.start:node.start_end]
        merged = " ".join(dict.fromkeys(node.cls + names))
        tag = set_attr(tag, "class", merged)
        if id(node) in styles:
            tag = set_attr(tag, "style", styles[id(node)], merge=True)
        edits.append((node.start, node.start_end - node.start, tag))
    out = source
    for edit in sorted(edits, key=lambda e: (e[0], len(e)), reverse=True):
        if len(edit) == 2:
            out = out[:edit[0]] + edit[1] + out[edit[0]:]
        else:
            out = out[:edit[0]] + edit[2] + out[edit[0] + edit[1]:]
    return out
