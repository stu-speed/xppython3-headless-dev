
## AI‑Assisted Coding for XPPython3

I have MS CoPilot Feb/2026 which has meaningful limitations for AI assisted coding. 
The biggest constraint is the **context window**: the session has a limited short‑term,
detailed memory (the active context) and a compressed, long‑term memory (context compression).
This guide documents what I learned from this project to get the most out of AI‑assisted coding within those constraints.

This AI generated guide merged what I found for XPPython3 coding with what has already been widely published.

This project provides a solid framework for creating fun X-plane AI generated code.

---

## 1. Establish design context before generating code

See all the AI generated guides in this project as an example.

Talk through the design with the AI before asking for implementation.  
This includes:

- describing the architecture  
- defining subsystem boundaries  
- explaining invariants and constraints  
- clarifying naming conventions  
- identifying what must *not* change  

Once the design is stable, have the AI generate a **README** with directory and file structure.  
This anchors the model’s context and prevents drift.

Regenerate the README periodically as the design evolves so the model’s context stays aligned.

---

## 2. Keep files focused and include explicit requirements

The AI generated simless libs in this project are broken out into many files with requirement comments on top.

AI performs best when each file has a **single, clear purpose**.  

At the top of every file, include a requirements block describing:
- the file’s role  
- invariants  
- must/must‑not rules  
- public API surface  
- typing expectations  

AI will honor these requirements consistently across regenerations.

---

## 3. Understand how AI treats old requirements

AI tends to preserve earlier constraints unless explicitly told otherwise.  

This means:
- old requirements remain in force  
- generated code stays backward‑compatible  
- the model avoids breaking earlier assumptions  

If a requirement is obsolete, explicitly tell the AI to ignore or remove it.

---

## 4. Avoid unnecessary indirection

AI is comfortable generating deep abstraction layers because it can track them easily.  
You cannot.  Don't let it.

Push back against:
- extra wrapper classes  
- unnecessary factories  
- redundant interfaces  
- over‑generalized patterns  

Keep the architecture simple and explicit.

---

## 5. Use strong typing everywhere

Give stubs.XPPython3.xp_typing.pyi and stubs.xp_interface.pyi files to AI model to follow.

Strong typing (preferably **mypy‑clean**) dramatically improves:
- AI’s ability to reason about your code  
- IDE code inspection  
- error detection  
- long‑term maintainability  

Do not accept AI‑generated code unless it passes IDE inspection and unit tests.  AI will
hallucinate methods that logically should exist but don't.

---

## 6. Generate tests while the context is fresh

See unit tests in this project as an example.

After implementing a feature, immediately ask the AI to generate:

- unit tests (see examples in project) 
- edge‑case tests  
- negative tests  
- integration tests (if applicable)

The model’s short‑term memory contains the most detail right after coding, so test generation is most accurate at this moment.

---

## 7. Use AI for debugging, but with guardrails

This whole project started so I can run plugins in an IDE debugger using the simless runner.

AI can interpret:

- stack traces  
- log output  
- error messages  

It can often identify obvious issues.  However, for deeper bugs:

- AI may confidently suggest incorrect or destructive changes  
- AI may misinterpret the root cause  
- AI may propose architectural rewrites you should not accept

Do these things to make AI debugging much more effective:
- ask AI to add debug logging to relevant methods
- Ask AI to identify all possible causes for the error instead of letting it confidently
stating it knows the exact reason and suggesting major changes as the proper course of action.
- Use the debugger to isolate suspicious values or states.  Once you have a concrete observation, give that specific detail to the AI for analysis.

---

## 8. Treat AI as a collaborator, not an authority

AI is excellent at:

- generating boilerplate  
- enforcing patterns  
- maintaining invariants  
- producing consistent code  
- accelerating iteration  

AI is **not** reliable at:

- architectural decisions  
- deep debugging  
- inferring missing requirements  
- validating correctness without tests  

You set the direction.  
AI accelerates execution of the plan.

