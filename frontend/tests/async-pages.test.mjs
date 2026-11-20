
import assert from 'node:assert/strict'
import test from 'node:test'

import {
    ASYNC_PAGE_DELAY,
    ASYNC_PAGE_TIMEOUT,
    createAsyncPageOptions,
    reloadAsyncPage,
} from '../src/asyncPages.js'

test('三个异步页面共用加载状态、错误状态与超时配置', () => {
    const loadingComponent = { name: 'AsyncPageLoading' }
    const errorComponent = { name: 'AsyncPageError' }

    const loaders = [
        () => Promise.resolve({ default: { name: 'IMDb' } }),
        () => Promise.resolve({ default: { name: 'Knowledge' } }),
        () => Promise.resolve({ default: { name: 'Detail' } }),
    ]

    for (const loader of loaders) {
        const options = createAsyncPageOptions(
            loader,
            loadingComponent,
            errorComponent
        )

        assert.equal(options.loader, loader)
        assert.equal(options.loadingComponent, loadingComponent)
        assert.equal(options.errorComponent, errorComponent)
        assert.equal(options.delay, ASYNC_PAGE_DELAY)
        assert.equal(options.timeout, ASYNC_PAGE_TIMEOUT)
    }
})

test('异步 loader 加载成功时保留页面组件', async () => {
    const view = { name: 'IMDb' }

    const options = createAsyncPageOptions(
        () => Promise.resolve({ default: view }),
        {},
        {}
    )

    const loaded = await options.loader()

    assert.equal(loaded.default, view)
})

test('异步 loader 加载失败时不会被配置函数吞掉', async () => {
    const failure = new Error('network unavailable')

    const options = createAsyncPageOptions(
        () => Promise.reject(failure),
        {},
        {}
    )

    await assert.rejects(
        options.loader(),
        (error) => error === failure
    )
})

test('整页重试调用浏览器 reload 一次', () => {
    let reloadCount = 0

    const browserWindow = {
        location: {
            reload: () => {
                reloadCount += 1
            },
        },
    }

    reloadAsyncPage(browserWindow)

    assert.equal(reloadCount, 1)
})

test('缺少浏览器 location 时重试明确抛错', () => {
    assert.throws(() => reloadAsyncPage({}), TypeError)
})