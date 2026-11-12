# Architecture

System components, the request flow for running an investigation, data modes, and the key technical decisions as built.

Filled in by #54.

## Unsupported questions

The interpretation prompt, [`copilot_core/prompts/interpret_v1.md`](../copilot_core/prompts/interpret_v1.md), tells Gemini to decline these questions. The reply then has `unsupported_reason` set and no findings, and the run is saved as `succeeded`, so the analyst sees why. The list follows the out-of-scope features in [plan.md section 5](plan.md#5-explicitly-out-of-scope) and the limits of the data:

- a forecast or prediction of future values (forecasting is out of scope)
- proof that one indicator causes another (causal inference claims are out of scope)
- a country that is not in the data (only African countries are covered)
- an indicator that is not in the supported list (`GET /api/indicators`)
- questions that need sources outside the data, such as news or web research (external web research is out of scope)
- anything that is not about the economic data, such as advice, opinions or writing tasks

The analyst's question is passed to Gemini between `<question>` tags and treated as data, not instructions, so a question that says "ignore previous instructions" changes nothing.
