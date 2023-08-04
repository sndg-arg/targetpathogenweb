// Webpack uses this to work with directories

const path = require('path');

// This is main configuration object.
// Here you write different options and tell Webpack what to do

module.exports = {

    // Path to your entry point. From this file Webpack will begin his work
    entry: './entrypoint.js',

    // Path and filename of your result bundle.
    // Webpack will bundle all JavaScript into this file
    output: {
        path: path.resolve(__dirname, './'),
        filename: 'bundle.js'
    },
    resolve: {
        alias: {
            handlebars: 'handlebars/dist/handlebars.min.js'
        },

    },
    node : {
        fs: 'empty',
    },
    module: {
        rules: [
            {
                test: /\.js/,
                exclude: /node_modules/,
                use: [
                    'babel-loader',
                    // 'eslint-loader',
                ],
            },
            {
                test: /\.css$/i,
                use: ['style-loader', 'css-loader'],
            },
            {
                test: /\.(png|jpe?g|gif|svg|eot|ttf|woff|woff2)$/i,
                loader: 'url-loader',
                options: {
                    limit: 8192,
                },
            },
        ],
    },

    // Default mode for Webpack is production.
    // Depending on mode Webpack will apply different things
    // on final bundle. For now we don't need production's JavaScript
    // minifying and other thing so let's set mode to development
    mode: 'development'
};
