"""Small, independently testable rules for the card browsing workspace."""

from anki.collection import SearchNode


def deck_query(col, name, include_children=True, text=""):
    """Use Anki's escaping; deck names may contain quotes and wildcards."""
    terms = []
    if name is not None:
        terms.append(SearchNode(deck=name))
        if not include_children:
            # SearchNode(deck=...) escapes literal wildcards. Append the one
            # intentional wildcard to the serialized, escaped deck expression.
            children = col.build_search_string(SearchNode(deck=name + "::"))
            if children.endswith('"'):
                children = children[:-1] + '*"'
            else:
                children += "*"
            terms.append(SearchNode(negated=SearchNode(parsable_text=children)))
    if text.strip():
        terms.append(SearchNode(parsable_text=text.strip()))
    return col.build_search_string(*terms) if terms else "deck:*"


def valid_sizes(value, count=2):
    return (
        isinstance(value, list)
        and len(value) == count
        and all(isinstance(v, int) and 40 <= v <= 10000 for v in value)
    )


class RequestGate:
    """Only the most recent requested result may replace the visible list."""

    def __init__(self):
        self.revision = 0

    def advance(self):
        self.revision += 1
        return self.revision

    def accepts(self, revision):
        return revision == self.revision
