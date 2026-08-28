import assert from 'node:assert/strict';
import { QA_SYSTEM_PROMPT } from '../ai/prompts';
import { loadSentriAiDomainSkill, validateDomainSkill } from '../ai/domainSkill';

const skill = loadSentriAiDomainSkill();
assert.match(skill, /^---\s*\nname: sentriai-operations/m);
assert.match(skill, /## Coverage policy/);
assert.match(skill, /NOT_REQUESTED/);
assert.ok(QA_SYSTEM_PROMPT.includes(skill), 'Gemini prompt must include the canonical skill verbatim');

assert.throws(
  () => validateDomainSkill('---\nname: sentriai-operations\n---\n# Bad'),
  /description/,
);
assert.throws(
  () => validateDomainSkill('---\nname: sentriai-operations\ndescription: valid test\n---\n# Missing policy'),
  /missing/,
);
assert.throws(
  () => loadSentriAiDomainSkill(['Z:/missing/sentriai/SKILL.md']),
  /domain skill is unavailable/,
);

console.log('SentriAI domain skill: PASS');
