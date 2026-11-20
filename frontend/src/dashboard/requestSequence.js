/**
 * 请求序号协调器：保证只有最新一次请求可以更新页面状态。
 */
export function createRequestSequence() {
  let latest = 0

  return {
    begin() {
      latest += 1
      return latest
    },
    isLatest(token) {
      return token === latest
    }
  }
}
