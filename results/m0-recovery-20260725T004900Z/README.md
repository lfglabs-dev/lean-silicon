# M0 recovery evidence

This directory records verification of the fixed-content commit
`c92bebc513c0654b68644f04236cd5a8f2fc71bd`. Its parent is
`9adc681c19202a05784f18d3d82508c07f7548c0` and its tree is
`904ad2a18b76855658a72fa1c7edc6d5bcb186ca`.

`status.tsv` contains the real exit code for each required command; the
matching `*.log` files contain the full command output. `proof-surface.log`
records Lean's axiom report for the selected public theorems. The source scan
checks that the project declares no `sorry`, `admit`, or `axiom` tokens in its
Lean proof surface.

This evidence is committed separately after testing. Consequently, the commit
that adds this directory has a different head SHA and must not be described as
the commit that was tested.
