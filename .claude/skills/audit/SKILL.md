---
name: audit
description: Audit the last code you wrote/ran for bugs and logic holes, fix them, and rerun
---

Stop. Critically audit the last code you wrote or ran.

1. **Re-read** the code you just wrote/ran — every line
2. **List** every bug, logic hole, edge case, off-by-one error, wrong assumption, or incorrect calculation you find. Be brutal — assume the code is wrong until proven right. Check:
   - Are loop bounds correct?
   - Are comparisons/thresholds making the right logical test?
   - Are array indices correct? Any off-by-one?
   - Are math operations correct (division, rounding, etc.)?
   - Are edge cases handled (empty input, single element, zero values)?
   - Are return values / output formats correct?
   - Does the code actually do what the user asked for, or did you subtly misinterpret the request?
   - Are there any silent failures or swallowed errors?
3. **Fix** every issue you found
4. **Rerun** the corrected code
5. **Show** what you changed and why
