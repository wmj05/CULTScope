
export const ASYNC_PAGE_DELAY = 200
export const ASYNC_PAGE_TIMEOUT = 15000

export function createAsyncPageOptions(loader, loadingComponent, errorComponent) {
    return {
        loader,
        loadingComponent,
        errorComponent,
        delay: ASYNC_PAGE_DELAY,
        timeout: ASYNC_PAGE_TIMEOUT,
    }
}

export function reloadAsyncPage(browserWindow) {
    browserWindow.location.reload()
}