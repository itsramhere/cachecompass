# Finite orchestration amendment — before continuation

The generic scripts/record_command.py has a hard-coded 180-second watchdog.
It killed the matrix parent after eight complete, validated, disposed cases.
The ninth child, tune3A, finished and sealed its data, but its parent could not
record exit/shutdown. Preserve it as incomplete orchestration evidence, exclude
it from selection, and execute exactly one linked replacement tune3A_r1.
The independent interrupted_matrix_shutdown.json verifies identity-checked
shutdown before continuation. No runtime/configuration/analysis source changed.

Continue the original finite cells only: reuse the eight cases with complete
command/source/shutdown/validation records, rerun tune3A once, then execute the
remaining fourteen never-started cells. Maximum 15 further measurements;
maximum 24 total for this review (23 eligible plus one preserved interrupted).
No added tuning points or changed selection criterion. The canonical source
remains 4e0941ac925840fe6e52b14d89163be562a11d944e8bee84887dabcde756a899.
continue_matrix.py records the exact resumption code and refuses existing
continuation outputs; each child retains the unchanged 90-second watchdog and
finally shutdown. The outer capture uses 2100 seconds. Selection is still saved
before fresh smoke and all failed settings remain visible. No data is rewritten.
