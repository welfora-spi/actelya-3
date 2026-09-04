// jsdom doesn't expose TextEncoder/TextDecoder as globals (react-router v7 needs them
// at import time), so polyfill from Node's util before anything else loads.
const { TextEncoder, TextDecoder } = require("util");
if (typeof global.TextEncoder === "undefined") global.TextEncoder = TextEncoder;
if (typeof global.TextDecoder === "undefined") global.TextDecoder = TextDecoder;

import "@testing-library/jest-dom";
