import type { DbConfigRequest } from '../types'

export const databaseTypeOptions = [
  { value: 'mysql', label: 'MySQL', defaultPort: 3306 },
  { value: 'postgresql', label: 'PostgreSQL', defaultPort: 5432 },
  { value: 'mongodb', label: 'MongoDB', defaultPort: 27017 },
  { value: 'mariadb', label: 'MariaDB', defaultPort: 3306 },
  { value: 'tidb', label: 'TiDB', defaultPort: 4000 },
  { value: 'doris', label: 'Doris', defaultPort: 9030 },
  { value: 'starrocks', label: 'StarRocks', defaultPort: 9030 },
  { value: 'oceanbase', label: 'OceanBase', defaultPort: 2881 },
  { value: 'oracle', label: 'Oracle', defaultPort: 1521 },
  { value: 'sqlserver', label: 'SQL Server', defaultPort: 1433 },
] as const

export type DatabaseTypeOption = (typeof databaseTypeOptions)[number]
export type DbConfigCredentialError = 'requiredFields' | 'mongoCredentialsPair' | 'relationalPasswordRequired'

export function requireDatabaseType(dbType: string | undefined): DatabaseTypeOption {
  const option = databaseTypeOptions.find((candidate) => candidate.value === dbType)
  if (!option) throw new Error(`Unsupported database type: ${String(dbType)}`)
  return option
}

export function validateDbConfigCredentials(
  dbType: string,
  username: string,
  password: string,
  isEditing: boolean,
): DbConfigCredentialError | null {
  const hasUsername = username.trim() !== ''
  const hasPassword = password.trim() !== ''
  if (dbType === 'mongodb') {
    return hasUsername === hasPassword ? null : 'mongoCredentialsPair'
  }
  if (!hasUsername) return 'requiredFields'
  if (!isEditing && !hasPassword) return 'relationalPasswordRequired'
  return null
}

export function normalizeBlankCredential(value: string): string {
  return value.trim() === '' ? '' : value
}

export function toDbConfigRequest(form: DbConfigRequest, dbType: DatabaseTypeOption['value']): DbConfigRequest {
  return {
    ...form,
    dbType,
    username: normalizeBlankCredential(form.username),
    password: normalizeBlankCredential(form.password),
  }
}