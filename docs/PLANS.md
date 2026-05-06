# Plans

## Active: Spec grilling

Current objective: resolve enough product/technical decisions to implement a small MVP without overbuilding.

### First decisions

1. URI and environment/profile model.
2. Modal SDK vs wrapping `modal volume` subprocess.
3. MVP command set.
4. Sidecar index scope.
5. JSON/error contract.

### Candidate MVP slice

- URI parser
- `ls`, `stat`, `cat --range`
- `index`, `find`, `manifest`
- JSON output
- SQLite sidecar metadata
- bounded content cache for text files
