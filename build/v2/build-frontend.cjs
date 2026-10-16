// DEV packaging keeps native assets unminified to avoid minifier worker OOM.
// Reuse the pinned upstream build script without patching upstream source.
const id = require.resolve('webpack', { paths: [process.cwd()] });
const webpack = require(id);
require.cache[id].exports = new Proxy(webpack, {
  apply(target, context, args) {
    args[0].optimization.minimize = false;
    // Native development defaults point async chunks at localhost:3001.
    args[0].output.publicPath = '/seafile/media/assets/frontend/';
    return Reflect.apply(target, context, args);
  },
});
