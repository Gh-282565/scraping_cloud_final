/*************************************************************************
* ADOBE CONFIDENTIAL
* ___________________
*
*  Copyright 2015 Adobe Systems Incorporated
*  All Rights Reserved.
*
* NOTICE:  All information contained herein is, and remains
* the property of Adobe Systems Incorporated and its suppliers,
* if any.  The intellectual and technical concepts contained
* herein are proprietary to Adobe Systems Incorporated and its
* suppliers and are protected by all applicable intellectual property laws,
* including trade secret and or copyright laws.
* Dissemination of this information or reproduction of this material
* is strictly forbidden unless prior written permission is obtained
* from Adobe Systems Incorporated.
**************************************************************************/
import state from"./state.js";import*as gmailResponseService from"./gmail-response-service.js";import{removeAllAcrobatTouchPoints,createURLForAttachment}from"./util.js";import{incrementDVSessionCount}from"../utils/util.js";const isDefaultViewershipFeatureForGmailEnabled=()=>state?.gmailConfig?.enableDefaultViewershipFeatureForGmail,isDefaultViewer=()=>isDefaultViewershipFeatureForGmailEnabled()&&state.isAcrobatDefaultForGmailPDFs&&chrome.runtime.id,takeDefaultViewerShip=()=>{isDefaultViewershipFeatureForGmailEnabled()&&!isDefaultViewer()&&(state.isAcrobatDefaultForGmailPDFs=!0,state?.resetDOMElementListener(),gmailResponseService.init(),removeAllAcrobatTouchPoints())},resetDefaultViewership=()=>{state.isAcrobatDefaultForGmailPDFs=!1,state?.resetDOMElementListener(),removeAllAcrobatTouchPoints(),gmailResponseService.init()},openPdfInNewTab=e=>{const t=createURLForAttachment(e.url,e.touchPoint,e.attachmentName);window.open(t,"_blank"),incrementDVSessionCount("gmail"),chrome.runtime.sendMessage({main_op:"akamai-ping"})};export{takeDefaultViewerShip,resetDefaultViewership,isDefaultViewer,openPdfInNewTab};