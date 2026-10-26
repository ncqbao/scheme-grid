'use strict';
const {contextBridge, ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('schemeGrid', Object.freeze({
  getInfo: () => ipcRenderer.invoke('sg:info'),
  openFile: () => ipcRenderer.invoke('sg:open'),
  arrange: options => ipcRenderer.invoke('sg:arrange', {numbering: !options || options.numbering !== false}),
  saveResult: () => ipcRenderer.invoke('sg:save'),
  openResult: () => ipcRenderer.invoke('sg:open-result'),
  cleanActive: options => ipcRenderer.invoke('sg:clean-active', {numbering: !options || options.numbering !== false})
}));
