"use client";

import { useEffect, useCallback, useRef, useState } from "react";
import { FormProvider } from "react-hook-form";
import { Button, Modal, useToast } from "@/panel/components/ui";
import { api } from "@/panel/api/client";
import { StepIndicator } from "./StepIndicator";
import { useInboundForm } from "./useInboundForm";
import { DEFAULT_PROTOCOLS } from "./protocols";
import { parseInboundToFormState } from "./parseInboundToFormState";
import { Step1Basics } from "./steps/Step1Basics";
import { Step2Protocol } from "./steps/Step2Protocol";
import { Step3Settings } from "./steps/Step3Settings";
import { Step4Stream } from "./steps/Step4Stream";
import { Step5Security } from "./steps/Step5Security";
import { Step6Sniffing } from "./steps/Step6Sniffing";
import { Step7Review } from "./steps/Step7Review";
import { defaultInboundFormState, type InboundFormState, type ProtocolDefinition } from "./types";
import "./inbound-modal.css";

interface InboundModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (
    config: InboundFormState,
    xrayJson: Record<string, unknown>,
    originalTag?: string,
  ) => void | Promise<void>;
  /** When set, modal opens in edit mode with fields populated from this inbound. */
  initialInbound?: Record<string, unknown> | null;
  originalTag?: string;
  allInbounds?: Record<string, unknown>[];
  protocols?: ProtocolDefinition[];
}

export function InboundModal({
  open,
  onClose,
  onSubmit,
  initialInbound = null,
  originalTag,
  allInbounds = [],
  protocols = DEFAULT_PROTOCOLS,
}: InboundModalProps) {
  const toast = useToast();
  const isEdit = Boolean(initialInbound);
  const {
    form,
    activeSteps,
    stepIndex,
    currentStepId,
    stepErrors,
    isRealityIncompatible,
    isHysteria,
    setStepIndex,
    setProtocol,
    setNetwork,
    setSecurity,
    generateRealityKeys,
    getXrayJson,
    validateAll,
    resetValidation,
    errorStepIndices,
  } = useInboundForm(protocols);

  const openRef = useRef(false);
  useEffect(() => {
    const justOpened = open && !openRef.current;
    openRef.current = open;
    if (!justOpened) return;

    resetValidation();
    if (initialInbound) {
      form.reset(parseInboundToFormState(initialInbound, protocols));
      const stream = (initialInbound.streamSettings || {}) as Record<string, unknown>;
      const sec = String(stream.security || "none");
      if (initialInbound.protocol === "shadowsocks" && sec !== "none") {
        toast.push(
          "This Shadowsocks inbound had Reality transport (not supported for SS). Saving will remove it — use VLESS+Reality for camouflage.",
          "info",
        );
      }
    } else {
      form.reset(defaultInboundFormState());
    }
    setStepIndex(0);
  }, [open, initialInbound, protocols, form, resetValidation, setStepIndex, toast]);

  const security = form.watch("security");
  const showFlow = security === "tls" || security === "reality";
  const isTun = form.watch("protocol") === "tun";

  const genWgKeys = useCallback(async () => {
    const kp = await api.get<{ privateKey: string; publicKey: string }>("/core/wireguard/keypair");
    form.setValue("wireguard.secretKey", kp.privateKey);
    if (form.getValues("wireguard.peers")[0] && !form.getValues("wireguard.peers")[0].publicKey) {
      form.setValue("wireguard.peers.0.publicKey", kp.publicKey);
    }
  }, [form]);

  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    const { ok, firstErrorIndex } = validateAll();
    if (!ok) {
      if (firstErrorIndex >= 0) setStepIndex(firstErrorIndex);
      toast.push("Please fix the highlighted fields", "error");
      return;
    }
    const values = form.getValues();
    const remark = values.basics.remark.trim();
    const port = values.basics.port.trim();
    const clash = allInbounds.some(
      (i) =>
        String(i.tag) !== (originalTag ?? "") &&
        (String(i.tag) === remark || String(i.port) === port),
    );
    if (clash) {
      toast.push("Tag or port already in use", "error");
      return;
    }
    setSaving(true);
    try {
      await onSubmit(values, getXrayJson(), originalTag);
      onClose();
    } catch {
      /* parent shows error toast */
    } finally {
      setSaving(false);
    }
  };

  const renderStep = () => {
    switch (currentStepId) {
      case "basics":
        return <Step1Basics form={form} errors={stepErrors} isTun={isTun} />;
      case "protocol":
        return <Step2Protocol form={form} protocols={protocols} setProtocol={setProtocol} />;
      case "settings":
        return (
          <Step3Settings
            form={form}
            protocols={protocols}
            errors={stepErrors}
            showFlow={showFlow}
            onGenerateWgKeys={genWgKeys}
          />
        );
      case "stream":
        return <Step4Stream form={form} errors={stepErrors} protocols={protocols} setNetwork={setNetwork} />;
      case "security":
        return (
          <Step5Security
            form={form}
            errors={stepErrors}
            protocols={protocols}
            setSecurity={setSecurity}
            isRealityIncompatible={isRealityIncompatible}
            isHysteria={isHysteria}
            generateRealityKeys={generateRealityKeys}
          />
        );
      case "sniffing":
        return <Step6Sniffing form={form} />;
      case "review":
        return (
          <Step7Review
            form={form}
            protocols={protocols}
            activeSteps={activeSteps}
            getXrayJson={getXrayJson}
            onEditStep={setStepIndex}
          />
        );
      default:
        return null;
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      dismissOnOverlay={false}
      formWide
      className="sk-inbound-wizard-shell"
      overlayClassName="sk-inbound-wizard-overlay"
      title={isEdit ? "Edit Inbound" : "Add Inbound"}
      footer={
        <div className="sk-inbound-wizard-foot">
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : isEdit ? "Save Inbound" : "Create Inbound"}
          </Button>
        </div>
      }
    >
      <div className="inbound-modal-theme">
        <StepIndicator
          activeSteps={activeSteps}
          currentIndex={stepIndex}
          errorSteps={errorStepIndices}
          onStepClick={setStepIndex}
        />
        <FormProvider {...form}>
          <div className="inbound-wizard-body">{renderStep()}</div>
        </FormProvider>
      </div>
    </Modal>
  );
}

/** @deprecated Use InboundModal — kept for existing imports */
export const AddInboundModal = InboundModal;
