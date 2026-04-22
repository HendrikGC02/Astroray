#pragma once
#include <string>

class Framebuffer; // defined in raytracer.h

class Pass {
public:
    virtual ~Pass() = default;

    // Called once after all pixels are accumulated.
    virtual void execute(Framebuffer& fb) = 0;

    // Display name for Blender UI.
    virtual std::string name() const = 0;
};
