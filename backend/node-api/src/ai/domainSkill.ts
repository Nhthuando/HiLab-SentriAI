import fs from 'node:fs';
import path from 'node:path';

const REQUIRED_SECTIONS = [
  '## Operating boundary',
  '## Domain vocabulary',
  '## Activity and policy semantics',
  '## Coverage policy',
  '## Evidence and clips',
  '## Answer workflow',
];

export function validateDomainSkill(content: string): string {
  const frontmatter = /^---\r?\n([\s\S]*?)\r?\n---\r?\n/.exec(content);
  if (!frontmatter) throw new Error('SentriAI domain skill has invalid frontmatter');
  const metadata = frontmatter[1];
  if (!/^name:\s*sentriai-operations\s*$/m.test(metadata)) {
    throw new Error('SentriAI domain skill has invalid name');
  }
  if (!/^description:\s*\S.+$/m.test(metadata)) {
    throw new Error('SentriAI domain skill is missing description');
  }
  for (const section of REQUIRED_SECTIONS) {
    if (!content.includes(section)) {
      throw new Error(`SentriAI domain skill is missing ${section.slice(3)}`);
    }
  }
  if (/\b(?:TODO|TBD)\b/i.test(content)) {
    throw new Error('SentriAI domain skill contains unresolved placeholders');
  }
  return content;
}

function defaultPaths(): string[] {
  return [
    path.resolve(__dirname, 'domain/sentriai-operations/SKILL.md'),
    path.resolve(process.cwd(), 'src/ai/domain/sentriai-operations/SKILL.md'),
    path.resolve(process.cwd(), 'backend/node-api/src/ai/domain/sentriai-operations/SKILL.md'),
  ];
}

export function loadSentriAiDomainSkill(candidatePaths = defaultPaths()): string {
  for (const candidate of candidatePaths) {
    if (!fs.existsSync(candidate)) continue;
    try {
      return validateDomainSkill(fs.readFileSync(candidate, 'utf8'));
    } catch (error) {
      throw new Error('SentriAI domain skill is invalid', { cause: error });
    }
  }
  throw new Error('SentriAI domain skill is unavailable');
}
