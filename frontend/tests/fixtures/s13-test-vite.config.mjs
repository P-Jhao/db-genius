import { mergeConfig } from 'vite'
import appConfig from '../../vite.config.ts'

const cacheDir = process.env.SQLCHAT_TEST_VITE_CACHE_DIR
if (!cacheDir) throw new Error('SQLCHAT_TEST_VITE_CACHE_DIR must point to an isolated test cache')

export default mergeConfig(appConfig, { cacheDir })